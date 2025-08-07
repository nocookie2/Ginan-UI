import ftplib
import os
from ftplib import FTP_TLS
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from app.utils.gn_functions import GPSDate
import numpy as np

# 1.Create an account with CDDIS EMAIL=<your_email> into "cddis.env" file in the same directory as this script.
# 2. Create a file named "cddis.env" in the same directory as this script
# 3. Add EMAIL=<your_account_email> to the "cddis.env" file

#Note: your email should be registered to cddis datetime :)
load_dotenv(Path(__file__).parent / "cddis.env")


def retrieve_all_cddis_types(reference_start: GPSDate) -> list[str]:
    """
    Retrieve all CDDIS data types for a given GPS Week.

    :param reference_start: The datetime of the GPS Week to retrieve.
    :param timespan: The duration for which to retrieve data.
    :return:
    """
    ftp_tls = FTP_TLS(host="gdc.cddis.eosdis.nasa.gov", user="anonymous", passwd=os.getenv("EMAIL"), timeout=60)
    ftp_tls.prot_p()  # Secures the TLS connection, mandatory for CDDIS
    files = None
    try:
        ftp_tls.cwd(f"gnss/products/{reference_start.gpswk}")
        files = ftp_tls.nlst()
    except ftplib.all_errors as e:
        print("Error getting file list", e)
    return files

def create_cddis_file(filepath: Path, reference_start: GPSDate) -> None:
    """
    Create a file named "CDDIS.list" with CDDIS data types for a given reference start time.

    :param filepath: The path to the directory where the file will be created.
    :param reference_start: The start time for the data retrieval.
    """
    data = retrieve_all_cddis_types(reference_start)
    with open(filepath.joinpath("CDDIS.list"), "w") as f:
        for d in data:
            try:
                time = datetime.strptime(d.split("_")[1], "%Y%j%H%M")
                f.write(f"{d} {time} \n")
            except IndexError:
                data.remove(d)


if __name__ == "__main__":
    start_time = GPSDate(np.datetime64(datetime(2023, 10, 1, 0, 0)))
    create_cddis_file(Path(__file__).parent, start_time)
