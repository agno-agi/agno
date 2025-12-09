#!/bin/bash

############################################################################
# Collection of helper functions to import in other scripts
############################################################################

space_to_continue() {
  read -n1 -r -p "Press Enter/Space to continue...  " key
  if [ "$key" = '' ]; then
    # Space pressed, pass
    :
  else
    exit 1
  fi
  echo ""
}

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
