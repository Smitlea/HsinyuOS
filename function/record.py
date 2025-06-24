import re
from datetime import datetime, date, timedelta
import json
import pytz

from flask_restx import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import joinedload
from static.models import db, Crane, User, CraneUsage, CraneNotice, CraneMaintenance, ConstructionSite, NoticeColor

from static.payload import (
    api_ns, api_crane, api_test, api_notice,
    general_output_payload,
)
from static.util import (
    handle_request_exception, save_photos, 
    photo_path_to_base64, delete_photo_file

)
from static.logger import logging


from static.payload import api
logger = logging.getLogger(__file__)


tz = pytz.timezone('Asia/Taipei')

