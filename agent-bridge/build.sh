#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
BAT_JDK="${BAT_JDK:-}"
if [ -z "$BAT_JDK" ]; then
  for candidate in "$ROOT"/runtime/*/Contents/Home; do
    if [ -x "$candidate/bin/javac" ]; then BAT_JDK="$candidate"; break; fi
  done
fi
if [ -z "$BAT_JDK" ]; then echo 'Set BAT_JDK to a Java 8 JDK directory.' >&2; exit 1; fi
mkdir -p "$HERE/build"
API_JAR="$ROOT/downloads/bat_interfaces.jar"
if [ -f "$API_JAR" ]; then
  API_CP="$API_JAR"
else
  # The public source bundle may omit BatMUD's compile-time API jar. Keep
  # the API-only stubs out of the plugin and use them only for compilation.
  STUB_BUILD="$HERE/build-stubs-compiled"
  mkdir -p "$STUB_BUILD"
  "$BAT_JDK/bin/javac" -source 8 -target 8 -d "$STUB_BUILD" "$HERE"/build-stubs/com/mythicscape/batclient/interfaces/*.java
  API_CP="$STUB_BUILD"
fi
"$BAT_JDK/bin/javac" -encoding UTF-8 -source 8 -target 8 -cp "$API_CP" -d "$HERE/build" "$HERE/src/local/batbridge/AgentBridge.java"
"$BAT_JDK/bin/jar" cf "$HERE/agent-bridge.jar" -C "$HERE/build" .
