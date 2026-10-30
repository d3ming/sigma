# Security

Report a vulnerability privately. Open the repo's **Security** tab and choose **Report a vulnerability**. This creates
a private security advisory that only you and the maintainer can see. Do not open a public issue or pull request for it.

Say what you found, how to reproduce it, and what it affects. The maintainer will reply there.

If you find a secret, a transcript, holdings, or copied newsletter text in the repo or its history, report it the same
way.

## What counts as private

Private: the owner's holdings and position sizes, contact details (phone, email, address), credentials, and the data in
the private repositories. Positions that posters share publicly about themselves are attributed source evidence.
The commit hooks and CI enforce this: a hashed private-word list, a check for any email address or phone number, and
gitleaks. Report anything that slipped through the same way as a secret.
