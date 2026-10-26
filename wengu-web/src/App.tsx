import { Navigate, Route, Routes } from "react-router-dom";

import AppLayout from "./components/AppLayout";
import CapturePage from "./pages/CapturePage";
import ExplainPage from "./pages/ExplainPage";
import GradingPage from "./pages/GradingPage";
import MistakeDetailPage from "./pages/MistakeDetailPage";
import MistakesPage from "./pages/MistakesPage";
import ReviewPage from "./pages/ReviewPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/capture" replace />} />
        <Route path="capture" element={<CapturePage />} />
        <Route path="capture/:captureId" element={<CapturePage />} />
        <Route path="grading/:gradingId" element={<GradingPage />} />
        <Route path="mistakes" element={<MistakesPage />} />
        <Route path="mistakes/:mistakeId" element={<MistakeDetailPage />} />
        <Route path="review" element={<ReviewPage />} />
        <Route path="explain" element={<ExplainPage />} />
        <Route path="*" element={<Navigate to="/capture" replace />} />
      </Route>
    </Routes>
  );
}
