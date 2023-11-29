import uvicorn
import time
import requests
import json

from tqdm import tqdm
from datetime import datetime

from pymongo import MongoClient
import meilisearch

from dotenv import load_dotenv
from os import getenv

load_dotenv()


def get_confirm_token(response):
    for key, value in response.cookies.items():
        if key.startswith("download_warning"):
            return value

    return None


def save_response_content(response, destination):
    chunk_size = 32 * 1024
    with open(destination, "wb") as f:
        for chunk in response.iter_content(chunk_size):
            if chunk:  # filter out keep-alive new chunks
                f.write(chunk)


def download_drive(file_id, destination):
    try:
        file = open(destination)
        file.close()
        return
    except:
        pass

    url = f"https://drive.google.com/uc?export=download&id={file_id}&confirm=t "
    session = requests.Session()

    response = session.get(url, params={"id": file_id}, stream=True)
    token = get_confirm_token(response)

    if token:
        params = {"id": file_id, "confirm": token}
        response = session.get(url, params=params, stream=True)

    save_response_content(response, destination)


def main():
    print(
        r"""
|---------------------------------------------|
    __               __                  __    
   / /_  ____ ______/ /_____  ____  ____/ /    
  / __ \/ __ `/ ___/ //_/ _ \/ __ \/ __  /     
 / /_/ / /_/ / /__/ ,< /  __/ / / / /_/ /      
/_.___/\__,_/\___/_/|_|\___/_/ /_/\__,_/       
         ______           __  ___    ____  ____
        / ____/___ ______/ /_/   |  / __ \/  _/
       / /_  / __ `/ ___/ __/ /| | / /_/ // /  
      / __/ / /_/ (__  ) /_/ ___ |/ ____// /   
     /_/    \__,_/____/\__/_/  |_/_/   /___/   
     
|---------------------------------------------|
    """
    )

    MONGO_SERVER_URL = getenv("MONGO_SERVER_URL")
    MONGO_BACKUP_URL = getenv("MONGO_BACKUP_URL")

    client = MongoClient(MONGO_SERVER_URL)
    companies = client["wallstreetlocal"]["companies"]
    companies_count = 852491

    MEILI_SERVER_URL = f'http://{getenv("MEILI_SERVER_URL")}:7700'
    MEILI_MASTER_KEY = getenv("MEILI_MASTER_KEY")

    try:
        retries = 3
        while retries:
            search = meilisearch.Client(MEILI_SERVER_URL, MEILI_MASTER_KEY)
            search.create_index("companies")
            companies_index = search.index("companies", {"primaryKey": "cik"})
            companies_index.add_documents([{"name": "TEST"}])
            retries -= 1
        raise RuntimeError
    except:
        search = meilisearch.Client(MEILI_SERVER_URL, MEILI_MASTER_KEY)
        companies_index = search.index("companies")
    search.get_keys()
    companies_index.update(primary_key="cik")

    db_empty = True if companies.count_documents({}) == 0 else False
    search_empty = (
        True if companies_index.get_stats().number_of_documents == 0 else False
    )
    backup_path = "./public/backup"

    def insert_database(document_list):
        try:
            companies.insert_many(document_list)
        except Exception as e:
            stamp = str(datetime.now())
            with open(f"{backup_path}/error-{stamp}.log", "w+") as f:
                f.write(str(e))
            print("Error Occured")

    def insert_search(document_list):
        try:
            companies_index.add_documents(document_list, "cik")
        except Exception as e:
            stamp = str(datetime.now())
            with open(f"{backup_path}/error-{stamp}.log", "w+") as f:
                f.write(str(e))
            print("Error Occured")

    if search_empty:
        print("[ Search (Meilisearch) Loading ] ...")

    if db_empty:
        print("[ Database (MongoDB) Loading ] ...")

    if db_empty or search_empty:
        file_path = f"{backup_path}/companies.bson"
        download_drive(MONGO_BACKUP_URL, file_path)

        batch = 4000
        database_documents = []
        search_documents = []
        progress = tqdm(
            total=companies_count, desc="Loading Documents", unit="document"
        )
        companies_bson = open(file_path, "rb")

        for line in companies_bson:
            document = json.loads(line.rstrip())
            document.pop("_id", None)

            database_count = len(database_documents)
            search_count = len(search_documents)

            if db_empty:
                database_documents.append(document)

                if database_count >= batch:
                    insert_database(database_documents)
                    progress.update(database_count)
                    database_documents = []

            if search_empty:
                search_documents.append(
                    {
                        "name": document.get("name"),
                        "tickers": document.get("tickers"),
                        "cik": document.get("cik"),
                        "thirteen_f": document.get("thirteen_f"),
                    }
                )

                if search_count >= batch:
                    insert_search(search_documents)
                    progress.update(search_count)
                    search_documents = []

        database_count = len(database_documents)
        search_count = len(search_documents)

        if search_empty and search_count:
            insert_search(search_documents)
            progress.update(search_count)
            search_documents = []
        if db_empty and database_count:
            insert_database(database_documents)
            progress.update(database_count)
            database_documents = []

        if search_empty:
            companies_index.update_displayed_attributes(
                [
                    "name",
                    "cik",
                    "tickers",
                ]
            )
            companies_index.update_searchable_attributes(["name", "tickers", "cik"])
            companies_index.update_filterable_attributes(["thirteen_f"])

        progress.close()
        companies_bson.close()

    if search_empty:
        print("[ Search (Meilisearch) Loaded ]")
    if db_empty:
        print("[ Database (MongoDB) Loaded ]")


workers = int(getenv("WORKERS"))  # type: ignore
port = 8000
host = "0.0.0.0"


def run(app):
    if workers == 1:
        uvicorn.run(app, host=host, port=port, forwarded_allow_ips="*", reload=True)
    else:
        uvicorn.run(app, host=host, port=port, forwarded_allow_ips="*", workers=workers)


# def initialize():
#     main()
#     # with daemon.DaemonContext():
#     #     main()

#     run("main:app")

#     # try:
#     #     loop = asyncio.get_running_loop()
#     # except RuntimeError:
#     #     loop = None

#     # if loop and loop.is_running():
#     #     loop.create_task(main())
#     # else:
#     #     asyncio.run(main())


if __name__ == "__main__":
    main()
    run("main:app")
