#!/usr/bin/env bash

curl -u user:password -v -F data.tar.gz=@data.tar.gz -F tasks.json=@split.json 127.0.0.1:5000/calculate
