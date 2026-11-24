B="/c/Program Files/Autodesk/Netfabb 2026/SIM/Solver/bin/pan2.exe"
for t in "$@"; do
  "$B" ${t}_thermal -s > ${t}_thermal.console 2>&1 || { echo "$t thermal failed"; exit 1; }
  "$B" ${t}_mechanical -s > ${t}_mechanical.console 2>&1 || { echo "$t mechanical failed"; exit 1; }
  echo "$t done"
done
