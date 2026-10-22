"""The native messaging host the Chrome extension calls to choose a tracked edition (feature 015;
contracts/native-host.md). It accepts three fixed commands, edits one line of [purchase_options] and reruns the
official report; the files it touches are fixed at install time, never named by a request."""
