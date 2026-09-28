class DatasetContextDetector:


    def detect(self, profile):


        signals = []


        columns = profile["columns"]


        column_names = [
            c["column_name"].lower()
            for c in columns
        ]


        numeric_columns = [
            c for c in columns
            if c["category"] == "numeric"
        ]


        categorical_columns = [
            c for c in columns
            if c["category"] == "categorical"
        ]



        network_keywords = [
            "protocol",
            "proto",
            "packet",
            "byte",
            "traffic",
            "flow",
            "connection",
            "service",
            "state"
        ]


        for word in network_keywords:

            if any(
                word in col
                for col in column_names
            ):

                signals.append(
                    "network_security"
                )

                break



        if len(numeric_columns) > 10:

            signals.append(
                "high_dimensional_telemetry"
            )



        if any(
            "attack" in col or
            "threat" in col
            for col in column_names
        ):

            signals.append(
                "security_dataset"
            )



        confidence = 0


        if signals:

            confidence = min(
                len(signals) / 3,
                1
            )



        return {

            "domain": 
                self.resolve_domain(signals),

            "signals":
                signals,

            "confidence":
                round(
                    confidence,
                    2
                )

        }



    def resolve_domain(self, signals):


        if "network_security" in signals:

            return "network_security"


        if "security_dataset" in signals:

            return "security_operations"


        return "unknown"