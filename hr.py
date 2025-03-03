from payload import api, api_ns, leave_payload, general_output_payload
from flask_restx import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, User, Leave
from util import handle_request_exception
from logger import logging

logger = logging.getLogger(__file__)



@api_ns.route('/api/requestleave', methods=['POST'])
class LeaveRequest(Resource):
    @handle_request_exception
    @api.expect(leave_payload)
    @api.marshal_with(general_output_payload)
    @jwt_required()
    def post(self):
        try:
            data = api.payload
            user_id = User.query.get(get_jwt_identity()).id
            start_date = data.get('start_date')
            end_date = data.get('end_date')
            reason = data.get('reason')
            
            new_leave_request = Leave(user_id=user_id, start_date=start_date, end_date=end_date, reason=reason)
            db.session.add(new_leave_request)
            db.session.commit()
            return {'status':'0', 'result': '新增成功'}
        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"Add LeaveRequest Error: [{error_class}] detail: {detail}")
            return {'status':'1', 'result': str(e)}
        