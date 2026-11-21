import { productPhoto } from "../../../../../lib/public-product";
export async function GET(
  _: Request,
  { params }: { params: Promise<{ id: string; position: string }> },
) {
  const { id, position } = await params;
  return productPhoto(id, position);
}
