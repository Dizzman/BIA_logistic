#!/usr/bin/env bash

set -e
source login.sh

oc apply -f gpn_logistic.yaml

