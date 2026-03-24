import { useQuery } from '@tanstack/react-query';
import { getLatestNews, getSentiment } from '../api/client';
import SentimentOrb from '../components/news/SentimentOrb';
import Card from '../components/ui/Card';
import { ErrorState, LoadingState } from '../components/ui/PageState';

export default function News() {
  const sentiment = useQuery({ queryKey: ['news-sentiment'], queryFn: getSentiment, refetchInterval: 120_000 });
  const latest = useQuery({ queryKey: ['news-latest'], queryFn: () => getLatestNews(20), refetchInterval: 120_000 });

  if (sentiment.isLoading || latest.isLoading) return <LoadingState message="Loading news..." />;
  if (sentiment.error || latest.error) return <ErrorState message="Unable to load news feeds." onRetry={() => { sentiment.refetch(); latest.refetch(); }} />;

  return (
    <div className="space-y-4">
      <Card>
        <h2 className="font-semibold mb-2">Sentiment</h2>
        <SentimentOrb sentiment={sentiment.data?.btc_sentiment} score={sentiment.data?.sentiment_score} />
      </Card>
      <Card>
        <h3 className="font-semibold mb-2">Latest Headlines</h3>
        <div className="space-y-2">
          {(latest.data?.articles || []).map((a, i) => <p className="text-sm" key={i}>• {a.title} <span className="text-zinc-500">({a.source})</span></p>)}
        </div>
      </Card>
    </div>
  );
}
