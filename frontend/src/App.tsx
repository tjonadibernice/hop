import { BrowserRouter, Route, Routes } from "react-router";
import AuthProvider from "./auth/AuthProvider";
import RequireAuth from "./auth/RequireAuth";
import Layout from "./components/Layout";
import HopPage from "./pages/HopPage";
import InterestsPage from "./pages/InterestsPage";
import LikesPage from "./pages/LikesPage";
import LoginPage from "./pages/LoginPage";
import SignupPage from "./pages/SignupPage";
import ReviewPage from "./pages/ReviewPage";
import VerifyEmailPage from "./pages/VerifyEmailPage";

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route
              index
              element={
                <RequireAuth>
                  <HopPage />
                </RequireAuth>
              }
            />
            <Route
              path="interests"
              element={
                <RequireAuth>
                  <InterestsPage />
                </RequireAuth>
              }
            />
            <Route
              path="likes"
              element={
                <RequireAuth>
                  <LikesPage />
                </RequireAuth>
              }
            />
            <Route
              path="review"
              element={
                <RequireAuth>
                  <ReviewPage />
                </RequireAuth>
              }
            />
            <Route path="login" element={<LoginPage />} />
            <Route path="signup" element={<SignupPage />} />
            <Route path="verify-email" element={<VerifyEmailPage />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
