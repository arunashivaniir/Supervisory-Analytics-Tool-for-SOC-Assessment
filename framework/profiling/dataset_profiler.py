import pandas as pd


class DatasetProfiler:


    def profile(self, file_path):

        df = pd.read_csv(file_path)


        result = {

            "dataset_summary": {

                "records":
                    int(len(df)),


                "columns":
                    int(len(df.columns)),


                "missing_percentage":
                    float(
                        round(
                            df.isnull()
                            .mean()
                            .mean()
                            * 100,
                            2
                        )
                    )

            },


            "columns": []

        }



        for column in df.columns:


            column_info = self.analyze_column(
                df[column]
            )


            column_info["column_name"] = column


            result["columns"].append(
                column_info
            )


        return result




    def analyze_column(self, series):


        info = {


            "data_type":
                str(series.dtype),


            "unique_values":
                int(series.nunique()),


            "null_values":
                int(series.isnull().sum())

        }



        # -------------------------------
        # Numeric Data
        # -------------------------------

        if pd.api.types.is_numeric_dtype(series):


            info.update({

                "category":
                    "numeric",


                "min":
                    float(series.min()),


                "max":
                    float(series.max()),


                "mean":
                    float(series.mean()),


                "std":
                    float(
                        series.std()
                        if pd.notna(series.std())
                        else 0
                    )

            })



        # -------------------------------
        # Datetime Data
        # -------------------------------

        elif pd.api.types.is_datetime64_any_dtype(series):


            info.update({

                "category":
                    "datetime"

            })



        else:


            values = (

                series
                .dropna()
                .astype(str)
                .unique()
                [:10]

            )


            sample_values = values.tolist()



            unique_ratio = (

                series.nunique()

                /

                len(series)

                if len(series) > 0

                else 0

            )



            avg_length = (

                sum(
                    len(value)
                    for value in sample_values
                )

                /

                len(sample_values)

                if sample_values

                else 0

            )



            column_name = (

                str(series.name)
                .lower()

            )



            # Common identifier patterns

            identifier_keywords = [

                "id",

                "host",

                "hostname",

                "asset",

                "device",

                "server",

                "system",

                "machine"

            ]



            has_identifier_keyword = any(

                keyword in column_name

                for keyword in identifier_keywords

            )



            # Avoid classifying normal categories
            # like HIGH, LOW, OPEN, CLOSED as IDs

            identifier_pattern = (

                unique_ratio > 0.8

                and avg_length >= 6

                and not self.is_common_category(
                    sample_values
                )

            )



            if (

                identifier_pattern

                or has_identifier_keyword

            ):


                info.update({

                    "category":
                        "identifier_like",


                    "sample_values":
                        sample_values

                })



            else:


                info.update({

                    "category":
                        "categorical",


                    "sample_values":
                        sample_values

                })



        return info




    def is_common_category(self, values):


        common_values = [

            "HIGH",

            "MEDIUM",

            "LOW",

            "CRITICAL",

            "OPEN",

            "CLOSED",

            "TRUE",

            "FALSE",

            "YES",

            "NO",

            "NORMAL"

        ]


        upper_values = [

            str(value).upper()

            for value in values

        ]


        return any(

            value in common_values

            for value in upper_values

        )