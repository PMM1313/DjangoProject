from .league import LeagueService
from .team import TeamService
from .stats import TrackingValues
from ..models import Team, Fixture, Country, League, Settings, ArchivedFixture, ForRecover, RecoverFixture


def process_extension_data():
    # process fixture data from provide and writes them to DB
    try:
        # find which site was scraped

        # decide which logic to use
        # for oddsportal, livescore, sofascore, etc ...

        # for each provider different function

        # return info data
        info = 'test'

    except Exception as e:
        # try except block and return errors if any
        return e

    return info


def process_scraped_oddsportal():
    return


def process_scraped_livescore():
    return
