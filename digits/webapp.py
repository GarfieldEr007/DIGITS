# Copyright (c) 2014-2016, NVIDIA CORPORATION.  All rights reserved.

import flask
from flask.ext.socketio import SocketIO

from digits import utils
from config import config_value
import digits.scheduler

### Create Flask, Scheduler and SocketIO objects

app = flask.Flask(__name__)
app.config['DEBUG'] = True
# Disable CSRF checking in WTForms
app.config['WTF_CSRF_ENABLED'] = False
# This is still necessary for SocketIO
app.config['SECRET_KEY'] = config_value('secret_key')
app.url_map.redirect_defaults = False
socketio = SocketIO(app)
scheduler = digits.scheduler.Scheduler(config_value('gpu_list'), True)

### Register filters and views

app.jinja_env.globals['server_name'] = config_value('server_name')
app.jinja_env.globals['server_version'] = digits.__version__
app.jinja_env.filters['print_time'] = utils.time_filters.print_time
app.jinja_env.filters['print_time_diff'] = utils.time_filters.print_time_diff
app.jinja_env.filters['print_time_since'] = utils.time_filters.print_time_since
app.jinja_env.filters['sizeof_fmt'] = utils.sizeof_fmt
app.jinja_env.filters['has_permission'] = utils.auth.has_permission
app.jinja_env.trim_blocks = True
app.jinja_env.lstrip_blocks = True

import digits.views

def username_decorator(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        this_username = flask.request.cookies.get('username', None)
        app.jinja_env.globals['username'] = this_username
        return f(*args, **kwargs)
    return decorated

for endpoint, function in app.view_functions.iteritems():
    app.view_functions[endpoint] = username_decorator(function)

### Setup the environment

scheduler.load_past_jobs()
