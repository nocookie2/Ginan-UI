import ftplib
import os
from ftplib import FTP_TLS
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
from app.utils.gn_functions import GPSDate
import numpy as np

#Hyuck a cddis EMAIL=<your_email> into "cddis.env" file in the same directory as this script.
#Note: your email should be registered to cddis datetime :)
load_dotenv(Path(__file__).parent / "cddis.env")

def retrieve_all_cddis_types(reference_start: GPSDate):
    """
    Retrieve all CDDIS data types for a given reference start time and timespan.

    :param reference_start: The start time for the data retrieval.
    :param timespan: The duration for which to retrieve data.
    :return:
    """
    ftp_tls = FTP_TLS(host="gdc.cddis.eosdis.nasa.gov", user="anonymous", passwd=os.getenv("EMAIL"), timeout=60)
    ftp_tls.prot_p() # puts the s in TLS
    files = None
    try:
        ftp_tls.cwd(f"gnss/products/{reference_start.gpswk}")
        files = ftp_tls.nlst()
    except ftplib.all_errors as e:
        print("Error getting file list", e)
    return files

if __name__ == "__main__":
    start_time = GPSDate(np.datetime64(datetime(2023, 10, 1, 0, 0)))
    lines = retrieve_all_cddis_types(start_time)[:-1] # Exclude the last line which is a blank line
    with open(Path(__file__).parent/"cddis_files.txt", "w") as f:
        for line in lines:
            try:
                time = datetime.strptime(line.split("_")[1], "%Y%j%H%M")
                f.write(f"{line} {time} \n")
            except IndexError:
                lines.remove(line)