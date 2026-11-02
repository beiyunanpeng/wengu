import { Navigate, Route, Routes } from "react-router-dom";

import AppLayout from "./components/AppLayout";
import BackupPage from "./pages/BackupPage";
import BankPage from "./pages/BankPage";
import DashboardPage from "./pages/DashboardPage";
import ImportPage from "./pages/ImportPage";
import IntakePage from "./pages/IntakePage";
import LocalSeedPage from "./pages/LocalSeedPage";
import MistakeDetailPage from "./pages/MistakeDetailPage";
import MistakesPage from "./pages/MistakesPage";
import PrintMistakesPage from "./pages/PrintMistakesPage";
import PrintPaperPage from "./pages/PrintPaperPage";
import PracticePage from "./pages/PracticePage";
import RecordsPage from "./pages/RecordsPage";
import ReviewPage from "./pages/ReviewPage";
import SchedulePage from "./pages/SchedulePage";
import { ParentSessionProvider } from "./parent/ParentSession";

export default function App() {
  return (
    <ParentSessionProvider>
      <Routes>
        <Route path="print/mistakes" element={<PrintMistakesPage />} />
        <Route path="print/paper" element={<PrintPaperPage />} />
        <Route element={<AppLayout />}>
          <Route index element={<Navigate to="/import" replace />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="import" element={<ImportPage />} />
          <Route path="intake" element={<IntakePage />} />
          <Route path="mistakes" element={<MistakesPage />} />
          <Route path="mistakes/:mistakeId" element={<MistakeDetailPage />} />
          <Route path="practice" element={<PracticePage />} />
          <Route path="review" element={<ReviewPage />} />
          <Route path="schedule" element={<SchedulePage />} />
          <Route path="records" element={<RecordsPage />} />
          <Route path="bank" element={<BankPage />} />
          <Route path="local-seed" element={<LocalSeedPage />} />
          <Route path="backup" element={<BackupPage />} />
          <Route path="*" element={<Navigate to="/import" replace />} />
        </Route>
      </Routes>
    </ParentSessionProvider>
  );
}
