class Solution {
public:

int firstOcc(vector<int>& arr, int key){
    int s = 0, e = arr.size()-1;
    int mid = s + (e-s) /2;
    int ans = -1;
    while (s<=e)
    {
        if(arr[mid] == key){
            ans = mid;
            e = mid - 1;
        }
        // right me jaao
        else if(key > arr[mid]){
            s = mid+1;
        }
        // left me jaao
        else{
            e = mid-1;
        }
        mid = s + (e-s)/2;
    }
    return ans;
    
}

int lastOcc(vector<int>& arr, int key){
    int s = 0, e = arr.size()-1;
    int mid = s + (e-s) /2;
    int ans = -1;
    while (s<=e)
    {
        if(arr[mid] == key){
            ans = mid;
            s = mid + 1;
        }
        // right me jaao
        else if(key > arr[mid]){
            s = mid+1;
        }
        // left me jaao
        else{
            e = mid-1;
        }
        mid = s + (e-s)/2;
    }
    return ans;
    
}
    vector<int> searchRange(vector<int>& nums, int target) {
    

        
    return {firstOcc(nums, target ), lastOcc(nums, target )};
    }
      
};
