#!/bin/bash

############################################################################
# Helper functions to import in other scripts
############################################################################

print_horizontal_line() {
  echo "------------------------------------------------------------"
}

print_heading() {
  print_horizontal_line
  echo "-*- $1"
  print_horizontal_line
}

print_info() {
  echo "-*- $1"
}
