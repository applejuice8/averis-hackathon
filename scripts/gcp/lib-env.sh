# env_value NAME FILE — NAME's value in a dotenv file: unquoted, without an
# inline " # comment". Prints nothing if absent. Callers must never echo it.
env_value() {
  local line
  line="$(grep -E "^[[:space:]]*$1=" "$2" | tail -n 1)" || true
  line="${line#*=}"
  line="${line%%[[:space:]]#*}"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  line="${line#[\"\']}"
  line="${line%[\"\']}"
  printf '%s' "$line"
}
