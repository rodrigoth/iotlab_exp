#!/bin/bash

tmux new-session -d -s "$1"

tmux send -t "$1" "$2" ENTER