import { redirect } from "next/navigation";

export default function Catalog() {
  redirect("/orders#start-a-claim");
}
