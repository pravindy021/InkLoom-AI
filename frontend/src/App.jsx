import { Navigate, Route, Routes } from "react-router-dom";
import AppShell from "./components/layout/AppShell";
import DashboardPage from "./pages/DashboardPage";
import ContentReviewPage from "./pages/ContentReviewPage";
import GuidelinesPage from "./pages/GuidelinesPage";
import ReviewQueuePage from "./pages/ReviewQueuePage";
import ReviewDetailPage from "./pages/ReviewDetailPage";
import AnalyticsPage from "./pages/AnalyticsPage";
import SettingsPage from "./pages/SettingsPage";
import SourcesPage from "./pages/SourcesPage";

export default function App() {
  return <Routes><Route element={<AppShell />}>
    <Route index element={<DashboardPage />} />
    <Route path="content/new" element={<ContentReviewPage />} />
    <Route path="reviews" element={<ReviewQueuePage />} />
    <Route path="reviews/:reviewId" element={<ReviewDetailPage />} />
    <Route path="guidelines" element={<GuidelinesPage />} />
    <Route path="sources" element={<SourcesPage />} />
    <Route path="analytics" element={<AnalyticsPage />} />
    <Route path="settings" element={<SettingsPage />} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Route></Routes>;
}
