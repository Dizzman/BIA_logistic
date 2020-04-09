#!/usr/bin/env bash

set -e
source login.sh

oc apply -f gpnla.yaml
oc apply -f gpnlb.yaml
