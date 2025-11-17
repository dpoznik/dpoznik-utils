#!/usr/bin/env python

"""List iNaturalist leaf taxa by first observation date.

Use case: When a user uploads a batch of observations and their species count increments
by some small number, it is interesting to learn which species are new.

"""

import csv
import json
import logging
import os
import time
from datetime import datetime, timedelta
from operator import itemgetter

import click
import requests
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

# Filepaths
CACHE_DIR = "./cache"
OUTPUT_DIR = "./output"
OBS_CACHE_FP_TP = os.path.join(CACHE_DIR, "observations.{username}.json")
OUTPUT_FP_TP = os.path.join(OUTPUT_DIR, "leaf_taxa.{username}.csv")

# Fetch parameters
OBS_API_URL = "https://api.inaturalist.org/v1/observations"
PER_PAGE = 200
SLEEP_BETWEEN_CALLS = 0.3
BACKOFF = 60

# iNaturalist constants
TAXON_URL_TP = "https://www.inaturalist.org/taxa/{taxon_id}"
INFRARANKS = {
    "subspecies",
    "variety",
    "form",
    "infraspecies",
    "subvariety",
    "subform",
    "cultivar",
    "race",
}

# Defaults
USERNAME_DEFAULT = os.environ["USER"]
NUM_TO_PRINT_DEFAULT = 30
UNKNOWN = "<Unknown>"

logger = logging.getLogger(__name__)
console = Console()


@click.command(context_settings={"show_default": True})
@click.help_option("-h", "--help")
@click.option("-u", "--username", default=USERNAME_DEFAULT)
@click.option("-n", "--num-to-print", default=NUM_TO_PRINT_DEFAULT)
def list_leaf_taxa_by_date(username: str, num_to_print: int) -> None:
    """List iNaturalist leaf taxa by first observation date."""

    configure_rich_logging()
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    observations = fetch_observations(username)
    taxon_id_to_info = {}
    taxon_id_to_date_first_observed: dict[str, str] = {}

    for observation in observations:
        taxon = observation.get("taxon")
        if not taxon:
            continue

        taxon_id = taxon["id"]
        ancestors = [
            ancestor_id
            for ancestor_id in (taxon.get("ancestor_ids") or [])
            if ancestor_id != taxon_id
        ]
        taxon_id_to_info[taxon_id] = {
            "id": taxon_id,
            "rank": taxon.get("rank"),
            "ancestor_ids": ancestors,
            "name": taxon.get("name"),
            "common_name": taxon.get("preferred_common_name", ""),
        }
        obs_date = observation.get("observed_on")
        if obs_date:
            taxon_id_to_date_first_observed[taxon_id] = (
                min(taxon_id_to_date_first_observed.get(taxon_id, obs_date), obs_date)
                if taxon_id in taxon_id_to_date_first_observed
                else obs_date
            )

    # Exclude ancestor taxa
    ancestor_ids = set()
    for taxon_info in taxon_id_to_info.values():
        ancestor_ids.update(taxon_info["ancestor_ids"])

    leaf_taxon_id_to_info = {
        taxon_id: taxon_info
        for taxon_id, taxon_info in taxon_id_to_info.items()
        if taxon_id not in ancestor_ids
    }

    # Collapse infra-species to species
    collapsed_taxon_id_to_info = {}
    for taxon_id, info in leaf_taxon_id_to_info.items():
        rank = (info["rank"] or "").lower()
        species_id = None
        if rank in INFRARANKS:
            for ancestor_id in reversed(info["ancestor_ids"]):
                if (
                    ancestor_id in taxon_id_to_info
                    and taxon_id_to_info[ancestor_id]["rank"] == "species"
                ):
                    species_id = ancestor_id
                    break

        if species_id:
            parent = taxon_id_to_info[species_id]
            parent_id = parent["id"]
            collapsed_taxon_id_to_info[parent_id] = parent
            taxon_id_to_date_first_observed[parent_id] = min(
                taxon_id_to_date_first_observed.get(parent_id, "9999-99-99"),
                taxon_id_to_date_first_observed.get(taxon_id, "9999-99-99"),
            )
        else:
            collapsed_taxon_id_to_info[taxon_id] = info

    final_leaf_taxon_id_to_info = collapsed_taxon_id_to_info
    num_leaf_taxa = len(final_leaf_taxon_id_to_info)
    sorted_leaf_taxon_id_info_tuples = sorted(
        final_leaf_taxon_id_to_info.items(),
        key=lambda taxon_id_info_tuple: taxon_id_to_date_first_observed.get(
            taxon_id_info_tuple[0],
            "9999-99-99",
        ),
    )

    column_name_style_tuples = [
        ("Index", "white"),
        ("Date", "cyan"),
        ("Common Name", "magenta"),
        ("Scientific Name", "magenta"),
        ("Rank", "white"),
        ("URL", "white"),
    ]
    column_names = map(itemgetter(0), column_name_style_tuples)
    table = Table()
    for column_name, style in column_name_style_tuples:
        table.add_column(column_name, style=style)

    if num_leaf_taxa == 0:
        return

    output_fp = OUTPUT_FP_TP.format(username=username)
    with open(output_fp, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(column_names)
        for i, (taxon_id, info) in enumerate(sorted_leaf_taxon_id_info_tuples, start=1):
            index = str(i)
            date = taxon_id_to_date_first_observed[taxon_id]
            common_name = title_case(info["common_name"]) or UNKNOWN
            scientific_name = title_case(info["name"]) or UNKNOWN
            rank = title_case(info["rank"])
            taxon_url = TAXON_URL_TP.format(taxon_id=taxon_id)
            row_values = [index, date, common_name, scientific_name, rank, taxon_url]
            writer.writerow(row_values)
            if i > num_leaf_taxa - num_to_print:
                table.add_row(*row_values)

    console.print(table)
    logger.info(f"\n✅ Saved {num_leaf_taxa} leaf taxa: {output_fp}\n")


def configure_rich_logging(log_fp: str | None = None) -> None:
    """Configure bare logging with RichHandler.

    Parameters
    ----------
    log_fp: str | None, optional
        File path to which to write log.

    """
    handlers: list[logging.Handler] = [
        RichHandler(
            markup=True,
            show_time=False,
            show_level=False,
            show_path=False,
        )
    ]
    if log_fp is not None:
        handlers.append(logging.FileHandler(log_fp, "w"))

    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=handlers)


def fetch_observations(username: str) -> list:
    """Fetch observations."""

    observations = []
    last_date = None

    obs_cache_fp = OBS_CACHE_FP_TP.format(username=username)
    if os.path.exists(obs_cache_fp):
        logger.info(f"\nLoading cached observations: {obs_cache_fp}...")
        with open(obs_cache_fp, encoding="utf-8") as file:
            observations = json.load(file)

        logger.info(f"Loaded {len(observations)} cached observations")
        dates = [
            observation.get("observed_on")
            for observation in observations
            if observation.get("observed_on")
        ]
        if dates:
            last_date = max(dates)
            logger.info(f"Last cached observation date: {last_date}")

    logger.info(f'\nFetching observations for "{username}"...')
    params: dict[str, str | int | bool] = {
        "user_id": username,
        "per_page": PER_PAGE,
        "order_by": "id",
        "order": "asc",
        "verifiable": "any",
        "quality_grade": "any",
        "geoprivacy": "any",
        "captive": "any",
        "spam": False,
    }
    if last_date:
        fetch_start_date = (
            datetime.fromisoformat(last_date) + timedelta(days=1)
        ).strftime("%Y-%m-%d")
        params["d1"] = fetch_start_date
        logger.info(f"Starting on: {fetch_start_date}")

    page = 1
    new_observations = []
    num_new_observations = 0
    valid_request = True

    while True:
        params["page"] = page
        response = requests.get(OBS_API_URL, params=params)
        if response.status_code == 429:
            logger.info("⚠️ Rate limited — pausing 60s...")
            time.sleep(BACKOFF)
            continue

        if response.status_code == 422:
            logger.error("❌ Invalid request. Try specifying username with `-u`.\n")
            valid_request = False
            break

        if response.status_code != 200:
            logger.info(f"⚠️ HTTP {response.status_code}, retrying in 5s...")
            time.sleep(5)
            continue

        results = response.json().get("results", [])
        if not results:
            break

        new_observations.extend(results)
        num_new_observations += len(results)
        logger.info(f"Fetched {num_new_observations} observations (page {page})")
        if len(results) < PER_PAGE:
            break

        page += 1
        time.sleep(SLEEP_BETWEEN_CALLS)

    if new_observations:
        existing_ids = {observation["id"] for observation in observations}
        merged_observations = observations + [
            observation
            for observation in new_observations
            if observation["id"] not in existing_ids
        ]
        logger.info(f"✅ Added {len(new_observations)} new observations")
        with open(obs_cache_fp, "w", encoding="utf-8") as file:
            json.dump(merged_observations, file, ensure_ascii=False, indent=2)

        logger.info(
            f"✅ Saved {len(merged_observations)} observations: {obs_cache_fp}\n"
        )

        return merged_observations
    else:
        if valid_request:
            logger.info("-- No new observations found --\n")

        return observations


def title_case(text: str) -> str:
    """Return title-case version of input."""

    return " ".join([word[0].upper() + word[1:] for word in text.split()])


if __name__ == "__main__":
    list_leaf_taxa_by_date()
