import subprocess
import webbrowser
import time
import os
import sys


def start_sat_sa():

    print("[+] Starting SAT-SA Security Analytics Platform")


    project_path = os.path.dirname(
        os.path.abspath(__file__)
    )


    dashboard_path = os.path.join(
        project_path,
        "dashboard",
        "app.py"
    )


    print("[+] Loading Supervisory Dashboard...")


    process = subprocess.Popen(

        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            dashboard_path
        ],

        stdout=subprocess.DEVNULL,

        stderr=subprocess.DEVNULL

    )


    time.sleep(5)


    webbrowser.open(

        "http://localhost:8501"

    )


    print("[+] SAT-SA Dashboard Started")



if __name__ == "__main__":

    start_sat_sa()