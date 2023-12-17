from flask import Blueprint

blueprint = Blueprint("scheduling", __name__)

@blueprint.route("/generate", methods=["GET"])
def generate_schedule():
    raise NotImplementedError()