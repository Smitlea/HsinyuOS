from datetime import datetime
import pytz

from flask import request
from flask_restx import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import selectinload  
from static.models import db, Crane, User, DailyTask, WorkRecord, TaskMaintenance, ConstructionSite, CraneAssignment

from static.payload import (
    api_ns, add_task_payload,
    general_output_payload, 
    add_task_maint_payload, 
    work_record_input_payload
)
from static.util import handle_request_exception
from static.logger import logging
