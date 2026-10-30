import { Navigate, Route, Routes } from "react-router-dom";

import AppLayout from "./components/AppLayout";
import DashboardPage from "./pages/DashboardPage";
import ImportPage from "./pages/ImportPage";
import IntakePage from "./pages/IntakePage";
import MistakeDetailPage from "./pages/MistakeDetailPage";
import MistakesPage from "./pages/MistakesPage";
import RecordsPage from "./pages/RecordsPage";
import ReviewPage from "./pages/ReviewPage";
import { ParentSessionProvider } from "./parent/ParentSession";

export default function App() {
  return (
    <ParentSessionProvider>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<Navigate to="/import" replace />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="import" element={<ImportPage />} />
          <Route path="intake" element={<IntakePage />} />
          <Route path="mistakes" element={<MistakesPage />} />
          <Route path="mistakes/:mistakeId" element={<MistakeDetailPage />} />
          <Route path="review" element={<ReviewPage />} />
          <Route path="records" element={<RecordsPage />} />
          <Route path="*" element={<Navigate to="/import" replace />} />
        </Route>
      </Routes>
    </ParentSessionProvider>
  );
}
