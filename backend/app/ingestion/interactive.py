"""Read a page as either an article or an interactive site.

Hop wants mostly interactive pages: tools, simulations, games, visualizations,
and playgrounds. Those have little article text (they're canvas, controls,
and JavaScript), so the article extractor alone would throw them away. This
module looks at the HTML for signs of interactivity, and for an interactive
page builds a short text profile (title, description, what's on the page,
visible text) that the AI screening and the curator can judge instead.

Only the HTML is read; nothing is rendered. A page built entirely in
JavaScript shows little more than its title and description, so a weak sign
is enough to keep it as a candidate, and the AI decides (see enrich.py).
"""

import re
from dataclasses import dataclass, field

import lxml.html
from lxml.etree import ParserError

from app.ingestion.extract import Extracted, canonical_link, extract_article
from app.models.page import ARTICLE, INTERACTIVE

MIN_ARTICLE_WORDS = 200  # an article needs this much text
MIN_PROFILE_WORDS = 12  # an interactive page needs at least a title and description
PROFILE_TEXT_WORDS = 600  # visible text kept in the profile
INTERACTIVE_SCORE = 4  # at this score a page is interactive
CANDIDATE_SCORE = 2  # with no article, this is enough for the AI to look

# Script names and APIs that mean graphics, games, or simulations
_RICH_SCRIPT = re.compile(
    r"three(\.module)?(\.min)?\.js|pixi|p5(\.min)?\.js|phaser|babylon|matter(\.min)?\.js"
    r"|\bd3(\.v\d)?(\.min)?\.js|plotly|vega|getContext\(\s*['\"](webgl2?|2d)['\"]"
    r"|WebAssembly|\.wasm\b|UnityLoader|godot|\bregl\b|tone(\.min)?\.js",
    re.IGNORECASE,
)
_WORDS_FOR_TOOLS = re.compile(
    r"\b(interactive|simulat\w*|playground|sandbox|game|puzzle|visuali[sz]\w*"
    r"|explorable|calculator|generator|editor|try it|play with|drag|tool)\b",
    re.IGNORECASE,
)
# Inputs that do something on the page (search, email, and text boxes are
# on every blog, so they don't count)
_WIDGET_INPUTS = {"range", "number", "color", "checkbox", "radio", "file"}
_SKIP_TEXT = ("script", "style", "noscript", "nav", "footer", "header", "template")


@dataclass(frozen=True)
class Signals:
    canvases: int = 0
    sliders: int = 0
    widgets: int = 0  # sliders, checkboxes, pickers, selects, text areas, editors
    buttons: int = 0  # outside forms, navigation, headers, and footers
    inline_svgs: int = 0
    rich_scripts: list[str] = field(default_factory=list)
    scripts: int = 0
    app_shell: bool = False  # an empty page that JavaScript fills in
    tool_words: bool = False  # the title or description says it's a tool/game/...
    game_type: bool = False  # <meta property="og:type" content="game">
    visible_words: int = 0
    title: str | None = None
    description: str | None = None
    headings: list[str] = field(default_factory=list)
    visible_text: str = ""

    @property
    def score(self) -> int:
        score = 0
        if self.canvases:
            score += 3
        if self.rich_scripts:
            score += 3
        if self.game_type:
            score += 3
        if self.sliders:
            score += 2
        if self.widgets >= 3:
            score += 2
        if self.buttons >= 6:
            score += 1
        if self.inline_svgs >= 3 and self.scripts:
            score += 1
        if self.app_shell:
            score += 2
        if self.tool_words:
            score += 1
        if self.visible_words >= 1500 and not (self.canvases or self.sliders):
            score -= 3  # a long read with a few gadgets is still an article
        return score

    def summary(self) -> str:
        """What's on the page, in a few words, e.g. "1 canvas, 4 sliders, uses three.js"."""
        parts = []
        for count, one, many in (
            (self.canvases, "canvas", "canvases"),
            (self.sliders, "slider", "sliders"),
            (self.widgets - self.sliders, "other control", "other controls"),
            (self.buttons, "button", "buttons"),
        ):
            if count > 0:
                parts.append(f"{count} {one if count == 1 else many}")
        if self.rich_scripts:
            parts.append("uses " + ", ".join(self.rich_scripts))
        if self.app_shell:
            parts.append("built with JavaScript (little text in the HTML)")
        return ", ".join(parts) or "no interactive elements found in the HTML"


@dataclass(frozen=True)
class ReadPage:
    kind: str  # ARTICLE or INTERACTIVE
    title: str | None
    text: str  # the article, or the profile of an interactive page
    canonical_url: str | None
    word_count: int
    signals: Signals


class Unreadable(Exception):
    """Neither an article nor an interactive page. reason: no_content or too_short."""

    def __init__(self, reason: str, detail: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def _meta(document, *names: str) -> str | None:
    for meta in document.iter("meta"):
        key = (meta.get("name") or meta.get("property") or "").lower()
        if key in names and (meta.get("content") or "").strip():
            return " ".join(meta.get("content").split())
    return None


def _inside(element, tags: tuple[str, ...]) -> bool:
    return any(parent.tag in tags for parent in element.iterancestors())


def page_signals(html: bytes) -> Signals:
    try:
        document = lxml.html.fromstring(html)
    except (ParserError, ValueError):
        return Signals()

    sliders = widgets = 0
    for element in document.iter("input"):
        kind = (element.get("type") or "text").lower()
        if kind in _WIDGET_INPUTS:
            widgets += 1
            sliders += kind == "range"
    widgets += len(document.findall(".//select")) + len(document.findall(".//textarea"))
    widgets += len(
        document.xpath("//*[@contenteditable and @contenteditable!='false']")
    )
    buttons = sum(
        1
        for button in document.iter("button")
        if not _inside(button, ("form", "nav", "header", "footer"))
    )

    scripts = list(document.iter("script"))
    rich = []
    for script in scripts:
        for match in _RICH_SCRIPT.finditer(
            (script.get("src") or "") + (script.text or "")
        ):
            name = match.group(0).split("(")[0].lower().removesuffix(".min.js")
            name = name.removesuffix(".js").strip(".")
            if name.startswith("getcontext"):
                name = "canvas drawing"
            if name not in rich:
                rich.append(name)

    title = (document.findtext(".//title") or "").strip() or _meta(document, "og:title")
    description = _meta(
        document, "description", "og:description", "twitter:description"
    )
    game_type = (_meta(document, "og:type") or "").lower() == "game"

    canvases = len(document.findall(".//canvas"))
    inline_svgs = len(document.findall(".//svg"))

    body = document.find(".//body")
    text = ""
    headings: list[str] = []
    if body is not None:
        # Menus, scripts, and footers aren't what the page is about
        for element in list(body.iter(*_SKIP_TEXT)):
            element.drop_tree()
        text = " ".join(body.text_content().split())
        headings = [
            " ".join(h.text_content().split())
            for h in body.iter("h1", "h2", "h3")
            if h.text_content().strip()
        ][:8]
    words = len(text.split())

    return Signals(
        canvases=canvases,
        sliders=sliders,
        widgets=widgets,
        buttons=buttons,
        inline_svgs=inline_svgs,
        rich_scripts=rich[:5],
        scripts=len(scripts),
        app_shell=words < 60 and len(scripts) >= 2,
        tool_words=bool(_WORDS_FOR_TOOLS.search(f"{title or ''} {description or ''}")),
        game_type=game_type,
        visible_words=words,
        title=title,
        description=description,
        headings=headings,
        visible_text=text,
    )


def profile(signals: Signals, article: Extracted | None) -> str:
    """The text an interactive page is judged by, in place of an article."""
    text = article.text if article is not None else signals.visible_text
    lines = [
        f"Interactive page: {signals.title or 'untitled'}",
        f"Description: {signals.description or 'none'}",
        f"What's on the page: {signals.summary()}",
    ]
    if signals.headings:
        lines.append("Headings: " + " | ".join(signals.headings))
    if text:
        lines.append("Text on the page: " + " ".join(text.split()[:PROFILE_TEXT_WORDS]))
    return "\n".join(lines)


def read_page(html: bytes, url: str) -> ReadPage:
    """The page as an article or an interactive site. Raises Unreadable."""
    article = extract_article(html, url)
    signals = page_signals(html)
    score = signals.score
    canonical = article.canonical_url if article else canonical_link(html, url)
    title = (article.title if article else None) or signals.title

    has_article = article is not None and article.word_count >= MIN_ARTICLE_WORDS
    if score >= INTERACTIVE_SCORE or (not has_article and score >= CANDIDATE_SCORE):
        text = profile(signals, article)
        words = len(text.split())
        if not (signals.title or signals.description) or words < MIN_PROFILE_WORDS:
            raise Unreadable("no_content", "interactive page with no description")
        return ReadPage(INTERACTIVE, title, text, canonical, words, signals)

    if article is None:
        raise Unreadable("no_content")
    if not has_article:
        raise Unreadable("too_short", f"{article.word_count} words")
    return ReadPage(
        ARTICLE, title, article.text, canonical, article.word_count, signals
    )
