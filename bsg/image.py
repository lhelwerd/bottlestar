from glob import glob
from pathlib import Path
from PIL import Image, ImageChops
import requests
from requests.exceptions import ConnectionError as ConnectError, HTTPError, Timeout
import yaml
from .card import Cards

class Images:
    """
    Handler for downloading images from BGG.
    """

    images = {}
    banners = {}
    _priorities = None

    @classmethod
    def normalize_name(cls, name):
        return name.replace("'", '').replace(' ', '').lower()

    @classmethod
    def load(cls):
        if cls.images:
            return

        with open("images.yml") as images_file:
            for data in yaml.safe_load_all(images_file):
                if data["type"].endswith("banners"):
                    cls.banners[data["type"]] = {
                        cls.normalize_name(name): image_id
                        for image_id, name in data["images"].items()
                    }

                text_format = data.get("format", "{}")
                for image_id, text in data["images"].items():
                    cls.images[image_id] = {
                        "formatted": text_format.format(text),
                        "text": text,
                        "titles": data.get("titles", [])
                    }

    def __init__(self, api_url):
        self.api_url = api_url
        self.session = requests.Session()
        self.load()

    @property
    def priorities(self):
        if self.__class__._priorities is None:
            self.__class__._priorities = {
                title.lower(): data['priority']
                for title, data in Cards.load().titles.items()
            }
            self.__class__._priorities.update({
                loyalty.lower(): data['priority']
                for loyalty, data in Cards.loyalty.items()
            })

        return self._priorities


    def retrieve(self, image_id, tags=False, download=True):
        """
        Retrieve an image by its ID. If an image is a known banner (either for
        a character or event), then a dictionary with the following items is
        returned:
        - "formatted": An alternative Markdown text
        - "text": Shorthand text
        - "titles": List of titles associated with the banner.
        If an image is already locally available then the path is returned.
        Otherwise, it is downloaded via the API to retrieve the URL and
        extension for the image, and the path is returned.
        Any failure (including if downloading is disabled) results in `None`.
        """

        if image_id in self.images:
            return self.images[image_id]

        if tags:
            return self.retrieve_tags(image_id)

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

    def retrieve_tags(self, image_id):
        """
        Retrieve the textual replacement for an alternative character banner.
        This uses the API to retrieve tags for the image, which are then
        compared to known banners to find the most appropriate dictionary of
        formatted Markdown text, shorthand text and titles. Any failure results
        in `None`.
        """

        request = self.session.get(f"{self.api_url}/images/{image_id}/tags")
        try:
            request.raise_for_status()
            result = request.json()
            sorted_tags = sorted(result['tags'], key=lambda tag: tag['count'])
            tags = [tag['rawtag'].lower() for tag in sorted_tags]
        except (ConnectError, HTTPError, Timeout, ValueError, KeyError):
            logging.exception("Could not look up tags for image ID %s",
                              image_id)
            return None

        banner_type = ""
        banner_priority = float('inf')
        characters = []
        for tag in tags:
            if not tag.startswith('bsg_'):
                continue

            name = tag[len('bsg_'):]
            if name == "banner" and banner_type == "":
                banner_type = "banners"
            elif self.priorities.get(name, banner_priority) < banner_priority:
                banner_type = f"{name}_banners"
                banner_priority = self.priorities[name]
            elif '_' not in name:
                characters.append(name)

        if banner_type not in self.banners:
            return None

        for character in characters:
            if character in self.banners[banner_type]:
                return self.images[self.banners[banner_type][character]]

        return None

    def banner(self, banner_type, name):
        """
        Retrieve a banner.
        """

        return self.banners.get(banner_type, {}).get(self.normalize_name(name))

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
