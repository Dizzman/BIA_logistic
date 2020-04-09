#!/usr/bin/env bash

curl -u user:password -v -F data.tar=@data.tar -F tasks.json=@merge.json 127.0.0.1:5000/calculate
