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
        self.images = {}
        self.banners = {}
        with open("images.yml") as images_file:
            for data in yaml.safe_load_all(images_file):
                if data["type"].endswith("banners"):
                    self.banners[data["type"]] = {
                        name: image_id
                        for image_id, name in data["images"].items()
                    }

                for image_id, text in data["images"].items():
                    text_format = data.get("format", "{}")
                    self.images[image_id] = text_format.format(text)

    def retrieve(self, image_id, download=True):
        """
        Retrieve an image by its ID. If an image is already locally available
        then the path is returned. Otherwise, it is downloaded using the API
        to retrieve the URL and extension for the image.
        """

        if image_id in self.images:
            return self.images[image_id]

        for image_path in glob(f"images/{image_id}.*"):
            return Path(image_path)

        if not download:
            return None

        request = self.session.get(f"{self.api_url}{image_id}")
        try:
            request.raise_for_status()
            result = request.json()
            extension = result["extension"]
            url = result["images"]["original"]["url"]
        except (ConnectError, HTTPError, Timeout, ValueError, KeyError):
            logging.exception("Could not look up information about image ID %s",
                              image_id)
            return None

        download = self.session.get(url, stream=True)
        image_path = Path(f"images/{image_id}.{extension}")
        with image_path.open("wb") as image_file:
            for chunk in download.iter_content(chunk_size=1024):
                image_file.write(chunk)

        return image_path

    def banner(self, banner_type, name):
        return self.banners.get(banner_type, {}).get(name)
