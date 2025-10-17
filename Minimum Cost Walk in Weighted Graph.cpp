class Solution {
public:
    vector<int> minimumCost(int n, vector<vector<int>>& edges, vector<vector<int>>& query) {
        vector<int> parent(n), min_path_cost(n, -1);
        iota(parent.begin(), parent.end(), 0);

        function<int(int)> find_root = [&](int node) {
            if (parent[node] != node) {
                parent[node] = find_root(parent[node]);
            }
            return parent[node];
        };

        for (auto& edge : edges) {
            int source = edge[0], target = edge[1], weight = edge[2];
            int source_root = find_root(source);
            int target_root = find_root(target);

            min_path_cost[target_root] &= weight;

            if (source_root != target_root) {
                min_path_cost[target_root] &= min_path_cost[source_root];
                parent[source_root] = target_root;
            }
        }

        vector<int> result;
        for (auto& q : query) {
            int start = q[0], end = q[1];
            if (start == end) {
                result.push_back(0);
            } else if (find_root(start) != find_root(end)) {
                result.push_back(-1);
            } else {
                result.push_back(min_path_cost[find_root(start)]);
            }
        }
        return result;
    }
};
