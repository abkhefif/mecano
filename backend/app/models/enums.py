import enum

# PERF-007: These enums are stored as VARCHAR columns in PostgreSQL. Native
# PG ENUM types would be more storage-efficient and provide DB-level value
# validation, but VARCHAR is acceptable at current scale and avoids the
# operational complexity of ALTER TYPE migrations when adding new values.


class UserRole(str, enum.Enum):
    MECHANIC = "mechanic"
    BUYER = "buyer"
    ADMIN = "admin"


class VehicleType(str, enum.Enum):
    CAR = "car"
    MOTORCYCLE = "motorcycle"
    UTILITY = "utility"


class BookingStatus(str, enum.Enum):
    PENDING_ACCEPTANCE = "pending_acceptance"
    CONFIRMED = "confirmed"
    AWAITING_MECHANIC_CODE = "awaiting_mechanic_code"
    CHECK_IN_DONE = "check_in_done"
    CHECK_OUT_DONE = "check_out_done"
    VALIDATED = "validated"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    DISPUTED = "disputed"


class ComponentStatus(str, enum.Enum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"


class FluidStatus(str, enum.Enum):
    OK = "ok"
    LOW = "low"
    EMPTY = "empty"


class BatteryStatus(str, enum.Enum):
    OK = "ok"
    WEAK = "weak"
    DEAD = "dead"


class SuspensionStatus(str, enum.Enum):
    OK = "ok"
    WORN = "worn"
    BROKEN = "broken"


class BodyStatus(str, enum.Enum):
    GOOD = "good"
    AVERAGE = "average"
    BAD = "bad"


class ExhaustStatus(str, enum.Enum):
    OK = "ok"
    RUST = "rust"
    HOLE = "hole"


class LightStatus(str, enum.Enum):
    OK = "ok"
    DEFECT = "defect"


class DriveBehavior(str, enum.Enum):
    NORMAL = "normal"
    SUSPECT = "suspect"
    DANGEROUS = "dangerous"


class Recommendation(str, enum.Enum):
    BUY = "buy"
    NEGOTIATE = "negotiate"
    AVOID = "avoid"


class UploadedBy(str, enum.Enum):
    MECHANIC = "mechanic"
    BUYER = "buyer"


class DisputeReason(str, enum.Enum):
    NO_SHOW = "no_show"
    WRONG_INFO = "wrong_info"
    RUDE_BEHAVIOR = "rude_behavior"
    OTHER = "other"


class DisputeStatus(str, enum.Enum):
    OPEN = "open"
    RESOLVED_BUYER = "resolved_buyer"
    RESOLVED_MECHANIC = "resolved_mechanic"
    CLOSED = "closed"


class ProposalStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REFUSED = "refused"
    COUNTER_PROPOSED = "counter_proposed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class NotificationType(str, enum.Enum):
    BOOKING_CREATED = "booking_created"
    BOOKING_CONFIRMED = "booking_confirmed"
    BOOKING_REFUSED = "booking_refused"
    BOOKING_CANCELLED = "booking_cancelled"
    CHECK_OUT_DONE = "check_out_done"
    BOOKING_DISPUTED = "booking_disputed"
    NEW_MESSAGE = "new_message"
    REMINDER = "reminder"
    NO_SHOW = "no_show"
    PROFILE_VERIFICATION = "profile_verification"
    PROPOSAL_RECEIVED = "proposal_received"
    PROPOSAL_ACCEPTED = "proposal_accepted"
    PROPOSAL_REFUSED = "proposal_refused"
    PROPOSAL_COUNTER = "proposal_counter"


class ServiceLocation(str, enum.Enum):
    MOBILE = "mobile"        # Mechanic goes to the client
    GARAGE = "garage"        # Client comes to mechanic's garage
    BOTH = "both"            # Both options available


class RefusalReason(str, enum.Enum):
    NOT_AVAILABLE = "not_available"
    TOO_FAR = "too_far"
    WRONG_VEHICLE = "wrong_vehicle"
    OTHER = "other"
