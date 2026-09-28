import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./app/AppShell";
import { OverviewPage } from "./pages/Overview";
import { AssessmentsPage } from "./pages/Assessments";
import { AssessmentDetailPage } from "./pages/AssessmentDetail";
import { FindingsPage } from "./pages/Findings";
import { EvidencePage } from "./pages/Evidence";
import { ReportsPage } from "./pages/Reports";

/**
 * The five screens, and nothing else.
 *
 * The dataset picker is not a route: it is the top bar's control, because
 * choosing a dataset is a property of the workspace rather than a page. A
 * completed run is owned by the shared analysis state, so a browser reload
 * lands on the same screen with the same run behind it.
 */
export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<OverviewPage />} />
        <Route path="/assessments" element={<AssessmentsPage />} />
        <Route path="/assessments/:assessmentId" element={<AssessmentDetailPage />} />
        <Route path="/findings" element={<FindingsPage />} />
        <Route path="/evidence" element={<EvidencePage />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
