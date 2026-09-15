"""Hand-written GraphQL. Counts come from `totalCount` (one number, no
enumeration); anything per-item is a bounded window sized by [api_windows]."""

REPO_OVERVIEW = """
query RepoOverview($owner: String!, $name: String!, $since: GitTimestamp!) {
  repository(owner: $owner, name: $name) {
    nameWithOwner
    stargazerCount
    forkCount
    isArchived
    isFork
    createdAt
    pushedAt
    hasIssuesEnabled
    watchers { totalCount }
    licenseInfo { spdxId }
    defaultBranchRef {
      name
      target { ... on Commit { history(since: $since) { totalCount } } }
    }
    openIssues: issues(states: OPEN) { totalCount }
    closedIssues: issues(states: CLOSED) { totalCount }
    openPRs: pullRequests(states: OPEN) { totalCount }
    mergedPRs: pullRequests(states: MERGED) { totalCount }
    closedPRs: pullRequests(states: CLOSED) { totalCount }
    labels { totalCount }
    milestones { totalCount }
    releases { totalCount }
  }
}
"""

OLDEST_OPEN_ISSUES = """
query OldestOpenIssues($owner: String!, $name: String!, $first: Int!) {
  repository(owner: $owner, name: $name) {
    issues(states: OPEN, first: $first, orderBy: {field: UPDATED_AT, direction: ASC}) {
      nodes { number createdAt updatedAt }
    }
  }
}
"""

RECENT_ISSUES = """
query RecentIssues($owner: String!, $name: String!, $first: Int!) {
  repository(owner: $owner, name: $name) {
    issues(first: $first, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes {
        number
        state
        createdAt
        closedAt
        authorAssociation
        labels { totalCount }
        milestone { number }
        comments(first: 10) { nodes { createdAt authorAssociation } }
      }
    }
  }
}
"""

RECENT_PULL_REQUESTS = """
query RecentPullRequests($owner: String!, $name: String!, $first: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequests(first: $first, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes {
        number
        state
        createdAt
        mergedAt
        closedAt
        authorAssociation
        labels { totalCount }
        reviews(first: 10) { totalCount nodes { submittedAt authorAssociation state } }
        comments(first: 10) { nodes { createdAt authorAssociation } }
      }
    }
  }
}
"""

RECENT_RELEASES = """
query RecentReleases($owner: String!, $name: String!, $first: Int!) {
  repository(owner: $owner, name: $name) {
    releases(first: $first, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes { tagName name publishedAt createdAt isPrerelease isDraft description }
    }
  }
}
"""

ISSUE_THREAD = """
query IssueThread($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      number title state createdAt closedAt authorAssociation body
      labels(first: 10) { nodes { name } }
      comments(first: 10) { totalCount nodes { createdAt authorAssociation body } }
    }
  }
}
"""

PULL_REQUEST_THREAD = """
query PullRequestThread($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      number title state createdAt mergedAt closedAt authorAssociation body additions deletions
      labels(first: 10) { nodes { name } }
      reviews(first: 10) { totalCount nodes { submittedAt authorAssociation state body } }
      comments(first: 10) { totalCount nodes { createdAt authorAssociation body } }
    }
  }
}
"""

RELEASE_BY_TAG = """
query ReleaseByTag($owner: String!, $name: String!, $tag: String!) {
  repository(owner: $owner, name: $name) {
    release(tagName: $tag) { tagName name publishedAt description }
  }
}
"""
