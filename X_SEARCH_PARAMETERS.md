# X (Twitter) API Search Parameters

## Current Parameters Used in Test Script

### API Call Parameters (`search_recent_tweets`)

```python
response = x_client.search_recent_tweets(
    query=query,                    # Search query string (required)
    max_results=100,                # Max tweets per request (10-100, default 10)
    start_time=start_time,          # ISO 8601 datetime - only tweets after this time
    tweet_fields=[...],             # Additional tweet data to include
    user_fields=[...],              # Additional user data to include
    expansions=[...],               # Related objects to include
    next_token=token                # For pagination (optional)
)
```

### Current Field Selections

**tweet_fields:**
- `created_at` - When the tweet was posted
- `public_metrics` - Likes, retweets, replies, quotes counts
- `author_id` - User ID of the tweet author
- `text` - Tweet content
- `referenced_tweets` - Info about retweets/quotes/replies

**user_fields:**
- `username` - @handle
- `name` - Display name

**expansions:**
- `author_id` - Include full user objects
- `referenced_tweets.id` - Include referenced tweet data

### Query String Operators

**Current query structure:**
```
from:username1 OR from:username2 (Tesla OR TSLA OR ...) -is:reply -is:retweet lang:en
```

**Available Query Operators:**

#### Account Filters
- `from:username` - Tweets from specific user
- `to:username` - Replies to specific user
- `@username` - Mentions specific user
- `retweets_of:username` - Retweets of specific user's tweets

#### Content Filters
- `keyword` - Contains keyword (case-insensitive)
- `"exact phrase"` - Exact phrase match
- `(A OR B)` - Either A or B
- `A AND B` - Both A and B
- `-keyword` - Excludes keyword

#### Tweet Type Filters
- `-is:retweet` - Exclude retweets
- `-is:reply` - Exclude replies
- `is:quote` - Only quote tweets
- `is:verified` - From verified accounts
- `has:links` - Contains links
- `has:media` - Contains media (images/videos)
- `has:hashtags` - Contains hashtags

#### Language & Location
- `lang:en` - English language
- `lang:es` - Spanish, etc.
- `place:country_code` - From specific country

#### Engagement Filters
- `min_faves:100` - At least 100 likes
- `min_retweets:10` - At least 10 retweets
- `min_replies:5` - At least 5 replies

#### Time Filters
- `since:YYYY-MM-DD` - Since date
- `until:YYYY-MM-DD` - Until date

### Query Limitations

- **Max query length:** 512 characters
- **Max results per request:** 100 tweets
- **Time window:** Last 7 days only (for `search_recent_tweets`)
- **Rate limits:** Varies by API tier

### Additional Available Parameters (Not Currently Used)

**tweet_fields (additional options):**
- `attachments` - Media attachments
- `author_id` - Author user ID
- `context_annotations` - Entity annotations
- `conversation_id` - Conversation thread ID
- `entities` - Hashtags, mentions, URLs
- `geo` - Geographic information
- `id` - Tweet ID
- `in_reply_to_user_id` - Reply target user ID
- `lang` - Language code
- `possibly_sensitive` - Content warning flag
- `public_metrics` - Engagement metrics
- `referenced_tweets` - Referenced tweet info
- `reply_settings` - Who can reply
- `source` - Client used to post
- `text` - Tweet text
- `withheld` - Content withholding info

**user_fields (additional options):**
- `created_at` - Account creation date
- `description` - Bio text
- `entities` - User entities
- `id` - User ID
- `location` - Location string
- `name` - Display name
- `pinned_tweet_id` - Pinned tweet
- `profile_image_url` - Profile picture
- `protected` - Private account flag
- `public_metrics` - Follower/following counts
- `url` - Profile URL
- `username` - @handle
- `verified` - Verified badge
- `withheld` - Account withholding info

**expansions (additional options):**
- `attachments.media_keys` - Media objects
- `attachments.poll_ids` - Poll objects
- `author_id` - User objects
- `edit_history_tweet_ids` - Edit history
- `entities.mentions.username` - Mentioned users
- `geo.place_id` - Place objects
- `in_reply_to_user_id` - Reply target users
- `referenced_tweets.id` - Referenced tweets
- `referenced_tweets.id.author_id` - Authors of referenced tweets

### Example Queries

**Current test script query:**
```
from:elonmusk OR from:Tesla OR ... (Tesla OR TSLA OR Model OR Cybertruck OR FSD OR Supercharger OR Giga OR Optimus OR Robotaxi OR 4680) -is:reply -is:retweet lang:en
```

**Alternative query (more permissive):**
```
(from:elonmusk OR from:Tesla OR from:Tesla_AI) (Tesla OR TSLA OR Model OR Cybertruck OR FSD) -is:reply lang:en
```

**Query with engagement filter:**
```
from:elonmusk (Tesla OR TSLA) min_faves:100 -is:retweet lang:en
```

### Pagination

To get more than 100 results, use `next_token`:

```python
response = x_client.search_recent_tweets(...)
next_token = response.meta.get('next_token')

if next_token:
    next_response = x_client.search_recent_tweets(
        ...,
        next_token=next_token
    )
```

### Rate Limits

- **Free tier:** 10,000 tweets/month
- **Basic tier:** 10,000 tweets/month  
- **Pro tier:** 1M tweets/month
- **Enterprise:** Custom limits

Rate limits are per 15-minute window and vary by endpoint.

