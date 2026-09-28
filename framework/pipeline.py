import sys


from framework.ingestion.ingestion_manager import IngestionManager

from framework.profiling.dataset_profiler import DatasetProfiler

from framework.intelligence.semantic_inference import SemanticInference

from framework.mapping.schema_mapper import SchemaMapper

from framework.features.adaptive_feature_engine import AdaptiveFeatureEngine

from framework.intelligence.mapping_report import MappingReport

from framework.intelligence.context.context_analyzer import DatasetContextAnalyzer

from framework.supervision.supervisory_engine import SupervisoryEngine

from framework.supervision.entity_evaluator import EntityEvaluator

from framework.assessment import AssessmentScopeBuilder

from framework.capability import CapabilityEvaluator, CapabilityRegistry

from framework.supervision.execution_gap_engine import ExecutionGapEngine
from framework.supervision.negative_space_detector import NegativeSpaceDetector
from framework.supervision.operational_pattern_detector import (
    OperationalPatternDetector,
)

from framework.ml.anomaly.isolation_forest_detector import (
    IsolationForestAnomalyDetector,
)




class SATSAPipeline:


    def __init__(self):


        self.profiler = DatasetProfiler()


        self.semantic_engine = SemanticInference(
            "framework/config/semantic_patterns.json"
        )


        self.context_analyzer = DatasetContextAnalyzer()


        self.mapper = SchemaMapper(
            "framework/config/mappings.json",
            "framework/canonical/canonical_schema.json"
        )


        self.ingestion = IngestionManager()


        self.feature_engine = AdaptiveFeatureEngine()


        self.mapping_report = MappingReport()


        self.supervisory_engine = SupervisoryEngine()


        self.entity_evaluator = EntityEvaluator()


        # Partitions records into (CSE, assessment period) scopes. This is a
        # data model only: it runs no analysis and changes no existing result.
        self.scope_builder = AssessmentScopeBuilder()


        # Reports which of the eight SOC capabilities each scope's submitted
        # evidence supports. Read-only over the existing result: it produces no
        # finding, no severity and no score.
        self.capability_registry = CapabilityRegistry()

        self.capability_evaluator = CapabilityEvaluator(
            self.capability_registry
        )



        # Detects contradictions between an expected control and the evidence
        # that was actually submitted, per assessment scope. Emits no severity
        # and no score, and its output is kept out of supervisory_findings so
        # the entity attention score is unchanged.
        self.execution_gap_engine = ExecutionGapEngine()

        self.negative_space_detector = NegativeSpaceDetector()

        self.operational_pattern_detector = OperationalPatternDetector()


        # Offline Isolation Forest anomaly discovery, per assessment scope.
        # Reads the same EvidenceIndex concept projection as the other
        # supervision layers and writes to its own result key, so it cannot
        # influence supervisory_findings, the attention score or any risk
        # value. scikit-learn is imported lazily inside the detector, so this
        # line never fails on a runtime that does not have it, and with no
        # trained artifact every scope is reported NOT_EVALUABLE rather than
        # guessed at.
        self.anomaly_detector = self._build_anomaly_detector()



    @staticmethod
    def _build_anomaly_detector():
        """Load the anomaly model if one has been trained, else stay inert.

        A missing artifact is the normal state before the training path has been
        run, and a missing scikit-learn is a deployment fact rather than an
        error. Neither is allowed to stop the pipeline: the layer reports
        itself unavailable and every scope comes back NOT_EVALUABLE.
        """

        try:

            detector = IsolationForestAnomalyDetector()

            if detector.registry.exists():
                detector.load()

            return detector

        except Exception:

            return IsolationForestAnomalyDetector()

    def run(self, dataset_file, evidence_id=None):


        print("[+] Loading dataset")


        ingestion = self.ingestion.load(
            dataset_file
        )



        try:


            print("[+] Profiling dataset")


            profile = self.profiler.profile(
                ingestion.profiling_target
            )



            print("[+] Running semantic inference")


            semantic_results = self.semantic_engine.infer(
                profile
            )



            print("[+] Understanding dataset context")


            dataset_context = self.context_analyzer.analyze(
                profile,
                semantic_results
            )



            mapping_report = self.mapping_report.generate(
                profile,
                semantic_results
            )



            # Generic multi-CSE / multi-period scope model. Runs silently so the
            # existing console summary is unchanged for single-dataset runs; the
            # result is exposed under the additional "assessment" key only.

            assessment = self.scope_builder.build(

                records=ingestion.records,

                profile=profile,

                semantic_results=semantic_results,

                source_id=ingestion.source,

                source_type=ingestion.source_type,

                evidence_id=evidence_id

            )



            # Evidence-aware capability context, evaluated per assessment scope.
            # Consumes canonical concepts and reads the existing result; no
            # pre-existing value is read-modified-written.

            capability_assessment = self.capability_evaluator.evaluate_collection(

                assessment,

                profile,

                semantic_results

            )



            # Evidence-backed execution-gap detection, evaluated per assessment
            # scope. Consumes the canonical concepts the capability layer
            # already resolved; reads no pre-existing result value and writes to
            # its own result key so the supervisory findings and the entity
            # attention score are untouched.

            execution_gap_findings = self.execution_gap_engine.evaluate_collection(

                assessment,

                profile,

                semantic_results,

                self.capability_evaluator

            )


            # Expected-evidence absence detection, evaluated per assessment
            # scope. Consumes the same canonical concepts, and the same
            # EvidenceIndex projection, as the execution-gap layer, but reports
            # the presence or absence of evidence rather than the value of a
            # submitted one. Reads no pre-existing result value and writes to
            # its own result key, so it cannot influence the supervisory
            # findings or the entity attention score.

            negative_space_findings = self.negative_space_detector.evaluate_collection(

                assessment,

                profile,

                semantic_results,

                self.capability_evaluator

            )


            # Operational pattern analysis: the shape of activity inside each
            # assessment scope, judged against that scope's own population.
            # Consumes canonical concepts through the same EvidenceIndex
            # projection as the other supervision layers. Emits no score, no
            # severity and no priority, and is not routed into the supervisory
            # findings or the attention scorer, so this layer cannot influence
            # any existing result value.

            operational_pattern_findings = (
                self.operational_pattern_detector.evaluate_collection(

                    assessment,

                    profile,

                    semantic_results,

                    self.capability_evaluator

                )
            )



            # Offline Isolation Forest anomaly discovery: whether a scope's
            # operational feature profile sits unusually far from a reference
            # population. Consumes the same canonical concepts and the same
            # EvidenceIndex projection as the layers above, judged one scope at
            # a time. Emits no severity, score, priority or confidence, is not
            # routed into supervisory_findings, and is not connected to the
            # attention scorer, so this layer cannot influence any existing
            # result value.

            anomaly_findings = self.anomaly_detector.evaluate_collection(

                assessment,

                profile,

                semantic_results,

                self.capability_evaluator

            )




            print("[+] Mapping dataset into SAT-SA schema")


            canonical_records = []



            for record in ingestion.records:


                mapped = self.mapper.map_record(
                    record,
                    semantic_results
                )


                canonical_records.append(
                    mapped
                )



            print("[+] Evaluating available features")


            feature_results = []



            for record in canonical_records:


                features = self.feature_engine.evaluate_available_features(
                    record
                )


                feature_results.append(
                    features
                )



            print("[+] Generating supervisory findings")


            supervisory_findings = self.supervisory_engine.analyse(
                canonical_records,
                dataset_context
            )



            print("[+] Generating entity assessment")


            entity_assessment = self.entity_evaluator.evaluate(
                canonical_records,
                supervisory_findings
            )



            result = {


                "dataset": dataset_file,


                "profile": profile,


                "semantic_mapping": semantic_results,


                "mapping_report": mapping_report,


                "dataset_context": dataset_context,


                "canonical_records": canonical_records,


                "feature_analysis": feature_results,

                "supervisory_findings": supervisory_findings,


                "entity_assessment": entity_assessment,


                "ingestion": ingestion.to_summary(),


                # Added by the assessment scope layer. The key is new, so no
                # pre-existing analytical result is altered.
                "assessment": assessment.to_dict(),


                # Added by the capability layer. Evidence availability per
                # assessment scope. Not a risk assessment.
                "capability_assessment": capability_assessment,


                # Added by the execution-gap layer. Evidence-backed
                # contradictions between an expected control and submitted
                # evidence, per assessment scope. Carries no severity and no
                # score, and is deliberately not merged into
                # supervisory_findings, which feeds the attention scorer.
                "execution_gap_findings": execution_gap_findings,


                # Added by the negative-space layer. Observable absence of
                # evidence that a configured expectation says should be
                # present, per assessment scope. Factual states only: no
                # severity, no score, no policy threshold, and no synthesis
                # with execution_gap_findings. Both keys describe the same
                # records from deliberately different angles.
                "negative_space_findings": negative_space_findings,


                # Added by the operational pattern layer. Distribution and
                # repetition of activity within each assessment scope, judged
                # against that scope's own population. Signals are qualified
                # POTENTIAL_OPERATIONAL_ANOMALY or reported NOT_EVALUABLE;
                # they carry no severity, score or priority, and are a separate
                # class of signal from execution gaps and negative space.
                "operational_pattern_findings": operational_pattern_findings,


                # Added by the offline anomaly layer. Whether each scope's
                # operational feature profile sits unusually far from a
                # reference population, decided by a trained Isolation Forest
                # and reported as POTENTIAL_OPERATIONAL_ANOMALY, NO_ANOMALY or
                # NOT_EVALUABLE. An independent supervisory signal: no
                # severity, no risk score, no attention score, no priority and
                # no confidence, and deliberately not connected to the
                # attention scorer. A scope without the evidence needed for a
                # feature vector is reported NOT_EVALUABLE and is never turned
                # into an anomaly.
                "anomaly_findings": anomaly_findings

            }




            # Populated only when the dataset was resolved through registered
            # evidence. Normal local use is unchanged and carries no
            # evidence_id field at all.


            if evidence_id:


                result["evidence_id"] = evidence_id


            return result


        finally:


            # Deletes any CSV the ingestion manager materialised for a
            # non-CSV source. A CSV source creates nothing to delete.


            self.ingestion.release(
                ingestion
            )





def print_summary(result):


    print(
        "\n========== SAT-SA SUPERVISORY SUMMARY ==========\n"
    )



    print(
        "Dataset:",
        result["dataset"]
    )


    if result.get("evidence_id"):


        print(
            "Evidence ID:",
            result["evidence_id"]
        )



    profile = result["profile"]



    print(
        "Records:",
        profile["dataset_summary"]["records"]
    )



    print(
        "Columns:",
        profile["dataset_summary"]["columns"]
    )



    print("\n----- Semantic Mapping -----")



    mappings = result["semantic_mapping"]


    print(
        "Mapped Columns:",
        len(mappings)
    )



    for item in mappings:


        print(
            f"{item['source_column']} --> "
            f"{item['canonical_concept']} "
            f"({item['confidence']})"
        )




    print("\n----- Dataset Context Understanding -----")


    for capability, details in result.get(
        "dataset_context",
        {}
    ).items():


        print(
            capability,
            "Confidence:",
            round(details["confidence"],2),
            "Evidence:",
            details["evidence"]
        )




    print("\n----- Mapping Coverage -----")


    report = result.get(
        "mapping_report",
        {}
    )


    print(
        "Overall Mapping Confidence:",
        report.get(
            "overall_mapping_confidence",
            0
        ),
        "%"
    )




    print("\n----- Feature Availability -----")


    feature_analysis = result.get(
        "feature_analysis",
        []
    )


    if feature_analysis:


        for feature in feature_analysis[0]:


            status = (
                "AVAILABLE"
                if feature["available"]
                else "MISSING"
            )


            print(
                feature["feature"],
                ":",
                status
            )




    print("\n----- Supervisory Findings -----")


    findings = result.get(
        "supervisory_findings",
        []
    )


    if findings:


        for finding in findings:


            print(
                "Indicator:",
                finding["indicator"]
            )


            print(
                "Severity:",
                finding["severity"]
            )


            print(
                "Reason:",
                finding["reason"]
            )

            print()


    else:


        print(
            "No supervisory indicators identified"
        )




    print("\n----- Entity Supervisory Assessment -----")


    entities = result.get(
        "entity_assessment",
        []
    )


    if entities:


        for entity in entities:


            print()


            print(
                "Entity:",
                entity["entity"]
            )


            print(
                "Records Analysed:",
                entity["records_analyzed"]
            )


            print(
                "Attention Score:",
                entity["attention_score"]
            )


            print(
                "Risk Level:",
                entity["risk_level"]
            )


            print(
                "Risk Indicators:",
                entity["risk_indicators"]
            )


    else:


        print(
            "No entity assessment available"
        )


    print(
        "\n=============================================="
    )




# ---------------------------------------------------------------------------
# Command line entry point
#
# Two modes, one analytical engine:
#
#   python -m framework.pipeline <dataset.csv>
#       Local development mode, unchanged. No evidence registration needed.
#
#   python -m framework.pipeline --from-evidence <EVIDENCE_ID>
#       Evidence mode. The identifier is resolved through the evidence
#       workspace, the preserved original is verified against its registered
#       SHA-256, and only the verified controlled working copy is analysed.
#       Analysis is aborted if verification does not succeed.
# ---------------------------------------------------------------------------


USAGE = (
    "Usage:\n"
    "  python -m framework.pipeline <dataset.csv>\n"
    "  python -m framework.pipeline --from-evidence <EVIDENCE_ID> "
    "[--evidence-root <dir>]"
)


class PipelineUsageError(Exception):
    """Raised for a malformed command line."""


def parse_arguments(argv):
    """Split the command line into dataset, evidence ID and evidence root.

    Anything that is not a recognised option is treated as the dataset path,
    exactly as before, so existing invocations behave identically.
    """

    dataset = None
    evidence_id = None
    evidence_root = None

    index = 0

    while index < len(argv):

        argument = argv[index]

        if argument in ("--from-evidence", "-e"):

            if index + 1 >= len(argv):

                raise PipelineUsageError(
                    f"{argument} requires an evidence ID"
                )

            evidence_id = argv[index + 1]
            index += 2
            continue


        if argument.startswith("--from-evidence="):

            evidence_id = argument.split("=", 1)[1]
            index += 1
            continue


        if argument == "--evidence-root":

            if index + 1 >= len(argv):

                raise PipelineUsageError(
                    "--evidence-root requires a directory"
                )

            evidence_root = argv[index + 1]
            index += 2
            continue


        if argument.startswith("--evidence-root="):

            evidence_root = argument.split("=", 1)[1]
            index += 1
            continue

        if argument in ("-h", "--help"):

            raise PipelineUsageError(None)


        if argument.startswith("-"):

            raise PipelineUsageError(
                f"Unknown option: {argument}"
            )


        if evidence_root is not None and not evidence_root.strip():

            raise PipelineUsageError(
                "--evidence-root requires a directory"
            )


        if dataset is None:

            dataset = argument


        index += 1


    # An explicitly supplied but empty option value is a usage error, not an
    # absent option: it must never silently fall back to local mode.
    if evidence_id is not None and not evidence_id.strip():

        raise PipelineUsageError(
            "--from-evidence requires an evidence ID"
        )


    return dataset, evidence_id, evidence_root




def print_evidence_failure(error):
    """Report a failed integrity check and the reason analysis stopped."""

    result = error.result

    print(
        "[!] Evidence integrity verification failed"
    )

    print(
        "[!] Status:",
        result.status.value
    )

    print(
        "[!] Subject:",
        error.subject
    )

    print(
        "[!] Path:",
        result.path
    )

    print(
        "[!] Expected SHA-256:",
        result.expected_sha256 or "unavailable"
    )

    print(
        "[!] Observed SHA-256:",
        result.observed_sha256 or "unavailable"
    )

    if result.detail:

        print(
            "[!] Detail:",
            result.detail
        )

    print(
        "[!] Analysis aborted"
    )




def run_from_evidence(evidence_id, evidence_root=None):
    """Resolve registered evidence, verify it, then analyse the working copy.

    Returns the SAT-SA result dictionary, or ``None`` if the evidence could
    not be resolved or failed verification. The analytical pipeline is only
    reached after the evidence is verified.
    """

    from framework.evidence.intake import (

        DEFAULT_WORKSPACE_ROOT,

        EvidenceError,

        EvidenceIntegrityError,

        EvidenceIntake

    )


    intake = EvidenceIntake(
        root=evidence_root or DEFAULT_WORKSPACE_ROOT
    )


    print("[+] Resolving evidence")


    try:


        identifier = intake.resolve_evidence_id(
            evidence_id
        )


    except EvidenceError as error:

        print(
            f"[!] {type(error).__name__}: {error}"
        )

        print("[!] Analysis aborted")

        return None


    print(
        "[+] Evidence ID:",
        identifier
    )


    print("[+] Verifying evidence integrity")


    try:


        resolved = intake.verify_analysis_target(
            identifier
        )


    except EvidenceIntegrityError as error:

        print_evidence_failure(error)

        return None


    except EvidenceError as error:

        print(
            f"[!] {type(error).__name__}: {error}"
        )

        print("[!] Analysis aborted")

        return None


    print(
        "[+] Integrity status:",
        resolved.original_integrity.status.value
    )


    print("[+] Loading controlled working copy")


    print(
        "[+] Working copy:",
        resolved.working_path
    )


    print("[+] Running SAT-SA analysis")


    pipeline = SATSAPipeline()


    return pipeline.run(

        str(resolved.working_path),

        evidence_id=resolved.evidence_id

    )




def main(argv=None):
    """Entry point for ``python -m framework.pipeline``."""

    arguments = list(
        sys.argv[1:] if argv is None else argv
    )


    try:


        dataset, evidence_id, evidence_root = parse_arguments(
            arguments
        )


    except PipelineUsageError as error:


        if error.args[0] is None:

            print(USAGE)

            return 0


        print(f"[!] {error.args[0]}")
        print(USAGE)

        return 2


    if evidence_id and dataset:

        print(
            "[!] Supply either a dataset file or --from-evidence, not both"
        )

        print(USAGE)

        return 2


    if evidence_id:


        result = run_from_evidence(
            evidence_id,
            evidence_root
        )


        if result is None:

            return 3


        print_summary(result)

        return 0


    if not dataset:

        print(USAGE)

        return 1


    pipeline = SATSAPipeline()


    result = pipeline.run(
        dataset
    )


    print_summary(result)


    return 0




if __name__ == "__main__":


    sys.exit(
        main()
    )