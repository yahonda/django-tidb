# Copyright 2021 PingCAP, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# See the License for the specific language governing permissions and
# limitations under the License.

import os

from django.db.models.signals import class_prepared

hosts = os.getenv("TIDB_HOST", "127.0.0.1")
port = os.getenv("TIDB_PORT", 4000)
user = os.getenv("TIDB_USER", "root")
password = os.getenv("TIDB_PASSWORD", "")

DATABASES = {
    "default": {
        "ENGINE": "django_tidb",
        "USER": user,
        "PASSWORD": password,
        "HOST": hosts,
        "PORT": port,
        "TEST": {
            "NAME": "django_tests",
            "CHARSET": "utf8mb4",
            "COLLATION": "utf8mb4_general_ci",
        },
        "OPTIONS": {
            "init_command": "SET @@tidb_allow_remove_auto_inc = ON",
        },
    },
    "other": {
        "ENGINE": "django_tidb",
        "USER": user,
        "PASSWORD": password,
        "HOST": hosts,
        "PORT": port,
        "TEST": {
            "NAME": "django_tests2",
            "CHARSET": "utf8mb4",
            "COLLATION": "utf8mb4_general_ci",
        },
        "OPTIONS": {
            "init_command": "SET @@tidb_allow_remove_auto_inc = ON",
        },
    },
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = False
SECRET_KEY = "django_tests_secret_key"

# Use a fast hasher to speed up tests.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]


def _require_json_null_default(sender, **kwargs):
    # model_fields.JSONNullDefaultModel uses db_default=JSONNull(), which TiDB
    # can't create. Declare the feature it needs, so that the test runner
    # doesn't create its table unless the server supports it. The tests that
    # use it are skipped in DatabaseFeatures.django_test_skips.
    if sender._meta.label == "model_fields.JSONNullDefaultModel":
        sender._meta.required_db_features = [
            *sender._meta.required_db_features,
            "supports_json_null_default",
        ]


class_prepared.connect(_require_json_null_default)
