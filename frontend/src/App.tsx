import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./app/AppShell";
import { AssessmentBuilderProvider } from "./app/AssessmentBuilder";
import { OverviewPage } from "./pages/Overview";
import { AssessmentsPage } from "./pages/Assessments";
import { NewAssessmentPage } from "./pages/NewAssessment";
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
 *
 * The assessment package (New Assessment) lives above the routes so it
 * survives navigation: starting a package, moving to Overview, and coming
 * back never discards the selection, and Overview can point at a package
 * that is ready for review instead of claiming nothing exists.
 */
export function App() {
  return (
    <AssessmentBuilderProvider>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/assessments" element={<AssessmentsPage />} />
          <Route path="/assessments/new" element={<NewAssessmentPage />} />
        <Route path="/assessments/:assessmentId" element={<AssessmentDetailPage />} />
        <Route path="/findings" element={<FindingsPage />} />
        <Route path="/evidence" element={<EvidencePage />} />
        <Route path="/reports" element={<ReportsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </AssessmentBuilderProvider>
  );
}
