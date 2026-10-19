"""The curator agent: reviews pages the automatic checks couldn't decide.

- tools.py:   read-only lookups the agent can call, and submit_decision
- prompts.py: the instructions and how the page is shown to the model
- model.py:   the tool-calling chat model, with provider failover
- graph.py:   the LangGraph loop (think, look up, decide)
- policy.py:  guardrails that turn the agent's proposal into a status
- service.py: runs one review and saves the result and its audit trail
"""
