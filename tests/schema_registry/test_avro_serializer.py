#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2020 Confluent Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
from struct import unpack
from io import BytesIO

import pytest

from confluent_kafka.schema_registry import (record_subject_name_strategy,
                                             SchemaRegistryClient,
                                             topic_record_subject_name_strategy)
from confluent_kafka.schema_registry.avro import AvroSerializer
from confluent_kafka.serialization import (MessageField,
                                           SerializationContext)

from .conftest import find_schema_id

# MockSchemaRegistryClient, see ./conftest.py for additional details.
TEST_URL = 'http://SchemaRegistry:65534'


def test_avro_serializer_config_auto_register_schemas():
    """
    Ensures auto.register.schemas is applied
    """
    conf = {'url': TEST_URL}
    test_client = SchemaRegistryClient(conf)
    test_serializer = AvroSerializer("string", test_client,
                                     conf={'auto.register.schemas': False})
    assert not test_serializer._auto_register


def test_avro_serializer_config_auto_register_schemas_invalid():
    """
    Ensures auto.register.schemas is applied
    """
    conf = {'url': TEST_URL}
    test_client = SchemaRegistryClient(conf)

    with pytest.raises(ValueError, match="must be a boolean"):
        AvroSerializer("string", test_client,
                       conf={'auto.register.schemas': dict()})


def test_avro_serializer_config_auto_register_schemas_false(mock_schema_registry):
    """
    Ensures auto.register.schemas=False does not register schema
    """
    conf = {'url': TEST_URL}
    test_client = mock_schema_registry(conf)
    topic = "test-auto-register"
    subject = topic + '-key'

    test_serializer = AvroSerializer("string", test_client,
                                     conf={'auto.register.schemas': False})

    test_serializer("test",
                    SerializationContext("test-auto-register",
                                         MessageField.KEY))

    register_count = test_client.counter['POST'].get('/subjects/{}/versions'
                                                     .format(subject), 0)
    assert register_count == 0
    # Ensure lookup_schema was invoked instead
    assert test_client.counter['POST'].get('/subjects/{}'.format(subject)) == 1


def test_avro_serializer_multiple_topic_per_serializer_instance(mock_schema_registry):
    """
    Ensures schema_id is correctly find when same serializer is used for multiple topics
    """
    conf = {'url': TEST_URL}
    test_client = mock_schema_registry(conf)
    topic1 = "test-topic1"
    topic2 = "test-topic2"

    test_serializer = AvroSerializer("string", test_client,
                                     conf={'auto.register.schemas': False})

    def ensure_id_match(ctx):
        subject = "{}-{}".format(ctx.topic, ctx.field)
        expected_id = find_schema_id(subject)

        payload = test_serializer("test", ctx)
        _, schema_id = unpack('>bI', BytesIO(payload).read(5))
        assert schema_id == expected_id

    ensure_id_match(SerializationContext(topic1, MessageField.KEY))
    ensure_id_match(SerializationContext(topic2, MessageField.VALUE))
    ensure_id_match(SerializationContext(topic1, MessageField.KEY))

    # Ensure lookup_schema was invoked only once per shema
    assert test_client.counter['POST'].get('/subjects/{}-key'.format(topic1)) == 1
    assert test_client.counter['POST'].get('/subjects/{}-value'.format(topic2)) == 1


def test_avro_serializer_preload_schema_id(mock_schema_registry):
    """
    Ensures serializer do not reload schema ID from registry after user has force its preloading.
    """
    conf = {'url': TEST_URL}
    test_client = mock_schema_registry(conf)
    topic1 = "test-topic1"
    topic2 = "test-topic2"

    test_serializer = AvroSerializer("string", test_client,
                                     conf={'auto.register.schemas': False})

    test_serializer.load_registry_schema_id(SerializationContext(topic1, MessageField.KEY))
    test_serializer.load_registry_schema_id(SerializationContext(topic2, MessageField.VALUE))

    # Ensure lookup_schema was invoked only once per shema
    assert test_client.counter['POST'].get('/subjects/{}-key'.format(topic1)) == 1
    assert test_client.counter['POST'].get('/subjects/{}-value'.format(topic2)) == 1

    test_serializer("test", SerializationContext(topic1, MessageField.KEY))
    test_serializer("test", SerializationContext(topic2, MessageField.VALUE))

    # Ensure we did not look again to avro registry
    assert test_client.counter['POST'].get('/subjects/{}-key'.format(topic1)) == 1
    assert test_client.counter['POST'].get('/subjects/{}-value'.format(topic2)) == 1


def test_avro_serializer_config_subject_name_strategy():
    """
    Ensures subject.name.strategy is applied
    """

    conf = {'url': TEST_URL}
    test_client = SchemaRegistryClient(conf)
    test_serializer = AvroSerializer("int", test_client,
                                     conf={'subject.name.strategy':
                                           record_subject_name_strategy})

    assert test_serializer._subject_name_func is record_subject_name_strategy


def test_avro_serializer_config_subject_name_strategy_invalid():
    """
    Ensures subject.name.strategy is applied
    """

    conf = {'url': TEST_URL}
    test_client = SchemaRegistryClient(conf)
    with pytest.raises(ValueError, match="must be callable"):
        AvroSerializer("int", test_client,
                       conf={'subject.name.strategy': dict()})


def test_avro_serializer_record_subject_name_strategy(load_avsc):
    """
    Ensures record_subject_name_strategy returns the correct record name
    """
    conf = {'url': TEST_URL}
    test_client = SchemaRegistryClient(conf)
    test_serializer = AvroSerializer(load_avsc('basic_schema.avsc'),
                                     test_client,
                                     conf={'subject.name.strategy':
                                           record_subject_name_strategy})

    ctx = SerializationContext('test_subj', MessageField.VALUE)
    assert test_serializer._subject_name_func(ctx,
                                              test_serializer._schema_name) == 'python.test.basic'


def test_avro_serializer_record_subject_name_strategy_primitive(load_avsc):
    """
    Ensures record_subject_name_strategy returns the correct record name.
    Also verifies transformation from Avro canonical form.
    """
    conf = {'url': TEST_URL}
    test_client = SchemaRegistryClient(conf)
    test_serializer = AvroSerializer('int',  test_client,
                                     conf={'subject.name.strategy':
                                           record_subject_name_strategy})

    ctx = SerializationContext('test_subj', MessageField.VALUE)
    assert test_serializer._subject_name_func(ctx,
                                              test_serializer._schema_name) == 'int'


def test_avro_serializer_topic_record_subject_name_strategy(load_avsc):
    """
    Ensures record_subject_name_strategy returns the correct record name
    """
    conf = {'url': TEST_URL}
    test_client = SchemaRegistryClient(conf)
    test_serializer = AvroSerializer(load_avsc('basic_schema.avsc'),
                                     test_client,
                                     conf={'subject.name.strategy':
                                           topic_record_subject_name_strategy})

    ctx = SerializationContext('test_subj', MessageField.VALUE)
    assert test_serializer._subject_name_func(
        ctx, test_serializer._schema_name) == 'test_subj-python.test.basic'


def test_avro_serializer_topic_record_subject_name_strategy_primitive(load_avsc):
    """
    Ensures record_subject_name_strategy returns the correct record name.
    Also verifies transformation from Avro canonical form.
    """
    conf = {'url': TEST_URL}
    test_client = SchemaRegistryClient(conf)
    test_serializer = AvroSerializer('int',
                                     test_client,
                                     conf={'subject.name.strategy':
                                           topic_record_subject_name_strategy})

    ctx = SerializationContext('test_subj', MessageField.VALUE)
    assert test_serializer._subject_name_func(
        ctx, test_serializer._schema_name) == 'test_subj-int'


def test_avro_serializer_subject_name_strategy_default(load_avsc):
    """
    Ensures record_subject_name_strategy returns the correct record name
    """
    conf = {'url': TEST_URL}
    test_client = SchemaRegistryClient(conf)
    test_serializer = AvroSerializer(load_avsc('basic_schema.avsc'),
                                     test_client)

    ctx = SerializationContext('test_subj', MessageField.VALUE)
    assert test_serializer._subject_name_func(
        ctx, test_serializer._schema_name) == 'test_subj-value'
