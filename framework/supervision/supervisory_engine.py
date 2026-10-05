from framework.supervision.execution_gap_engine import (
    ExecutionGapEngine
)


class SupervisoryEngine:


    def __init__(self):

        self.execution_engine = ExecutionGapEngine()



    def analyse(
            self,
            records,
            context
    ):


        findings = []


        execution_findings = self.execution_engine.evaluate(

            records,

            context

        )


        findings.extend(

            execution_findings

        )


        return findings