import { Navigate, Route, Routes } from "react-router-dom";
import RequireAuth from "./components/auth/RequireAuth";
import AppShell from "./components/layout/AppShell";
import DashboardPage from "./pages/DashboardPage";
import ContentReviewPage from "./pages/ContentReviewPage";
import GuidelinesPage from "./pages/GuidelinesPage";
import ReviewQueuePage from "./pages/ReviewQueuePage";
import ReviewDetailPage from "./pages/ReviewDetailPage";
import AnalyticsPage from "./pages/AnalyticsPage";
import SettingsPage from "./pages/SettingsPage";
import SourcesPage from "./pages/SourcesPage";
import LoginPage from "./pages/LoginPage";
import ChangePasswordPage from "./pages/ChangePasswordPage";
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import ResetPasswordPage from "./pages/ResetPasswordPage";
import AcceptInvitationPage from "./pages/AcceptInvitationPage";
import AdminPage from "./pages/AdminPage";
import RequireAdmin from "./components/auth/RequireAdmin";

export default function App() {
  return <Routes>
    <Route path="login" element={<LoginPage />} />
    <Route path="forgot-password" element={<ForgotPasswordPage />} />
    <Route path="reset-password" element={<ResetPasswordPage />} />
    <Route path="accept-invitation" element={<AcceptInvitationPage />} />
    <Route element={<RequireAuth />}>
      <Route path="change-password" element={<ChangePasswordPage />} />
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="content/new" element={<ContentReviewPage />} />
        <Route path="reviews" element={<ReviewQueuePage />} />
        <Route path="reviews/:reviewId" element={<ReviewDetailPage />} />
        <Route path="guidelines" element={<GuidelinesPage />} />
        <Route path="sources" element={<SourcesPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route element={<RequireAdmin />}>
          <Route path="admin" element={<AdminPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Route>
  </Routes>;
}
