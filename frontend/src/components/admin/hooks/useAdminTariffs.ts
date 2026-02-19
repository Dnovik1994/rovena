import { useQuery } from "@tanstack/react-query";

import { fetchAdminTariffs } from "../../../services/resources";
import { AdminTariff } from "../../../types/admin";

export const useAdminTariffs = (token: string) => {
  return useQuery<AdminTariff[]>({
    queryKey: ["admin-tariffs"],
    queryFn: () => fetchAdminTariffs(token),
    enabled: Boolean(token),
  });
};
