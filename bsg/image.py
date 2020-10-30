from glob import glob
from pathlib import Path
from PIL import Image, ImageChops
import requests
from requests.exceptions import ConnectionError as ConnectError, HTTPError, Timeout
import yaml

class Images:
    """
    Handler for downloading images from BGG.
    """

    images = {}
    banners = {}

    @classmethod
    def load(cls):
        if cls.images:
            return

        with open("images.yml") as images_file:
            for data in yaml.safe_load_all(images_file):
                if data["type"].endswith("banners"):
                    cls.banners[data["type"]] = {
                        name: image_id
                        for image_id, name in data["images"].items()
                    }

                text_format = data.get("format", "{}")
                for image_id, text in data["images"].items():
                    cls.images[image_id] = (text_format.format(text), text)

    def __init__(self, api_url):
        self.api_url = api_url
        self.session = requests.Session()
        self.load()

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

        # Retrieve the API data for the image.
        request = self.session.get(f"{self.api_url}/images/{image_id}")
        try:
            request.raise_for_status()
            result = request.json()
            extension = result["extension"]
            url = result["images"]["original"]["url"]
        except (ConnectError, HTTPError, Timeout, ValueError, KeyError):
            logging.exception("Could not look up information about image ID %s",
                              image_id)
            return None

        return self.download(url, f"{image_id}.{extension}")

    def download(self, url, filename):
        """
        Download an image from a URL to the local storage.
        Returns the Path of the local file.
        """

        download = self.session.get(url, stream=True)
        image_path = Path(f"images/{filename}")
        with image_path.open("wb") as image_file:
            for chunk in download.iter_content(chunk_size=1024):
                image_file.write(chunk)

        return image_path

    def banner(self, banner_type, name):
        """
        Retrieve a banner.
        """

        return self.banners.get(banner_type, {}).get(name)

    def crop(self, path, target_path=None, bbox=None):
        if target_path is None:
            target_path = path

        image = Image.open(path)
        if bbox is None:
            background = Image.new(image.mode, image.size,
                                   color=image.getpixel((0, 0)))
            diff = ImageChops.difference(image, background)
            bbox = diff.getbbox()

        if bbox:
            safe_bbox = (max(0, bbox[0] - 5), max(0, bbox[1] - 5),
                         min(image.size[0], bbox[2] + 5),
                         min(image.size[1], bbox[3] + 5))
            image.crop(safe_bbox).save(target_path)
