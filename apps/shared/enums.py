from enum import StrEnum


class OlxCategory(StrEnum):
    LONG_TERM = "long_term_apt"        # Долгосрочная аренда квартир
    ROOMS = "rooms"                    # Аренда комнат
    DAILY = "daily"                    # Посуточно (only if user opts in)
    LOOKING_FOR = "looking_for"        # "Сниму"


class ListingState(StrEnum):
    PENDING_ENRICH = "pending_enrich"
    ACTIVE = "active"
    DEAD = "dead"


class SearchType(StrEnum):
    WHOLE_APT_FAMILY = "whole_apt_family"
    WHOLE_APT_SOLO = "whole_apt_solo"
    SHARED_ROOM = "shared_room"
    LOOKING_FOR_ROOMMATE = "looking_for_roommate"


class GenderConstraint(StrEnum):
    ANY = "any"
    MALE = "male"
    FEMALE = "female"


class BathroomType(StrEnum):
    PRIVATE = "private"
    SHARED = "shared"
    UNKNOWN = "unknown"


class PosterRole(StrEnum):
    OWNER = "owner"
    AGENT = "agent"
    UNKNOWN = "unknown"
