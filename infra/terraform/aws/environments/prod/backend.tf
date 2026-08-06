terraform {
  # v0.9 validates the production declaration without applying it. If a live
  # production environment is created, migrate this root to its own encrypted
  # remote backend and lock table before the first collaborative apply.
  #
  # Never share the dev or test state with this root.
}
