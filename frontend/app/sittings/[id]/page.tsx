import { SittingReader } from "@/components/SittingReader";

/**
 * Full reading view of a single plenary sitting. A thin server component: it
 * awaits the dynamic `params` (a Promise in this Next.js) and hands the id to
 * the client reader, which fetches and renders the parsed transcript.
 */
export default async function SittingPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <SittingReader id={id} />;
}
