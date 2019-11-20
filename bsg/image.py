from glob import glob
from pathlib import Path
import requests
from requests.exceptions import ConnectionError as ConnectError, HTTPError, Timeout
import yaml

class Images:
    """
    Handler for downloading images from BGG.
    """

    def __init__(self, api_url):
        self.api_url = api_url
        self.session = requests.Session()
        with open("images.yml") as images_file:
            self.images = yaml.safe_load(images_file)

    def retrieve(self, image_id, download=True):
        """
        Retrieve an image by its ID. If an image is already locally available
        then the path is returned. Otherwise, it is downloaded using the API
        to retrieve the URL and extension for the imae.
        """

        if image_id in self.images:
            return self.images[image_id]

        for image_path in glob(f"images/{image_id}.*"):
            return Path(image_path)

        if not download:
            return None

        request = self.session.get(f"{self.api_url}{image_id}")
        print(request.headers)
        try:
            request.raise_for_status()
            result = request.json()
            extension = result["extension"]
            url = result["images"]["original"]["url"]
        except (ConnectError, HTTPError, Timeout, ValueError, KeyError):
            loggin.exception("Could not look up information about image ID %s",
                             image_id)
            return None

        download = self.session.get(url, stream=True)
        image_path = Path(f"images/{image_id}.{extension}")
        with image_path.open("wb") as image_file:
            for chunk in download.iter_content(chunk_size=1024):
                image_file.write(chunk)

        return image_path
